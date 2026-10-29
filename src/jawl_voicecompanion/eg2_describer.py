"""Detailed multi-level EG2 sensory describer.

Replaces the heavy autoregressive VLM with a deterministic Coarse-to-Fine (NCM)
pipeline over EmbeddingGemma 2 vectors + NumPy DSP + in-memory Windows OCR:

  L0: macro domain (screen type / audio type / active app / gaming mode)
  L1: facets (visual style, 5-zone spatial layout, music genre/instrument/rhythm/
      key/mode, speech style, mood, co-watching etiquette)
  L2: grounded lexical (OCR text, UIA elements, ASR transcript, DSP metrics)

The same pass feeds:
  - describe_screen (replaces VLM for screen questions)
  - describe_displays (multi-display detailed description)
  - describe_audio (music/speech/SFX with DSP metrics)
  - describe_system_audio (loopback audio description)
  - perception_snapshot (3-ring self-awareness state for JAWL brain context)

All heavy lifting stays on CPU via ONNX int4 + pure NumPy; no raw media is
retained beyond the request boundary.
"""

from __future__ import annotations

import io
import hashlib
import json
import math
import subprocess
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .audio_understanding import safe_detailed_audio_claim

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EG2_ONNX_ROOT = (
    ROOT / "runtime" / "models" / "embeddinggemma-2-onnx"
)

# ---------------------------------------------------------------------------
# Concept banks: each is a tuple of (label, text_prompt, emotion)
# Text prompts are embedded by EmbeddingGemma 2 text encoder into 768-D vectors
# and stacked into a matrix for cosine-similarity classification.
# ---------------------------------------------------------------------------

VISUAL_STYLE_BANK: tuple[tuple[str, str, str], ...] = (
    ("dark_ide_terminal", "title: none | text: dark themed code editor IDE terminal with syntax highlighted source code and console output", "attentive"),
    ("youtube_video_page", "title: none | text: YouTube website in web browser with video player recommendations and comments", "happy"),
    ("anime_video_player", "title: none | text: anime episode or movie playing in a video player with subtitles and characters", "happy"),
    ("game_3d_action", "title: none | text: three dimensional video game with combat action HUD overlay and 3D graphics", "excited"),
    ("desktop_application", "title: none | text: desktop application window with panels buttons menus and toolbars", "neutral"),
    ("media_player", "title: none | text: media player showing video with playback controls timeline and volume", "relaxed"),
    ("chat_messenger", "title: none | text: chat messenger or messaging application with conversation bubbles and avatars", "attentive"),
    ("system_dashboard", "title: none | text: system dashboard or task manager with graphs metrics and process list", "neutral"),
    ("web_article", "title: none | text: web page with article text images and hyperlinks on light background", "neutral"),
)

VISUAL_ELEMENT_BANK: tuple[tuple[str, str, str], ...] = (
    ("code_editor", "title: none | text: code editor with syntax highlighted programming text", "attentive"),
    ("terminal_console", "title: none | text: command line terminal with shell output and prompt", "attentive"),
    ("web_page", "title: none | text: web browser page with hyperlinks and formatted content", "neutral"),
    ("video_frame", "title: none | text: video frame showing animated scene or live footage", "happy"),
    ("chat_bubble", "title: none | text: chat message bubble with text conversation", "attentive"),
    ("button_control", "title: none | text: clickable button control element in a user interface", "neutral"),
    ("tab_bar", "title: none | text: tab bar with multiple open tabs in a browser or IDE", "neutral"),
    ("sidebar_panel", "title: none | text: sidebar panel with navigation or file tree", "neutral"),
    ("error_dialog", "title: none | text: error dialog or warning message with red alert", "surprised"),
    ("menu_dropdown", "title: none | text: dropdown menu with list of options", "neutral"),
)

AudioConceptEntry = tuple[str, str | tuple[str, ...], str]

AUDIO_SCENE_BANK: tuple[AudioConceptEntry, ...] = (
    (
        "music_present",
        (
            "title: none | text: music is audible, with melody, rhythm, instruments, or sustained musical tones",
            "title: none | text: a musical performance or soundtrack can be heard in the recording",
            "title: none | text: a music bed with acoustic instruments or electronic tones plays in the audio",
        ),
        "relaxed",
    ),
    (
        "speech_dominant",
        (
            "title: none | text: one person or several people speak as the foreground sound",
            "title: none | text: conversational speech or narration is prominent in the audio",
            "title: none | text: a spoken voice carries most of the audible scene",
        ),
        "attentive",
    ),
    (
        "environmental_sounds",
        (
            "title: none | text: environmental ambience, natural sounds, machinery, or game effects are audible",
            "title: none | text: the recording contains room ambience and environmental sound events",
            "title: none | text: mechanical, nature, or game sound effects form the audible scene",
        ),
        "neutral",
    ),
    (
        "speech_and_music",
        (
            "title: none | text: human speech and a musical soundtrack overlap in the same recording",
            "title: none | text: voices and background music are both audible at once",
            "title: none | text: spoken dialogue is heard over music playing underneath",
        ),
        "attentive",
    ),
)

MUSIC_GENRE_BANK: tuple[AudioConceptEntry, ...] = (
    ("classical_piano", "title: none | text: classical piano music with melodic phrases and soft dynamics", "relaxed"),
    ("electronic_ambient", "title: none | text: electronic ambient music with synthesizer pads and slow tempo", "relaxed"),
    ("rock_energetic", "title: none | text: energetic rock music with electric guitar drums and fast tempo", "excited"),
    ("jazz_smooth", "title: none | text: smooth jazz music with saxophone and walking bass", "relaxed"),
    ("pop_vocal", "title: none | text: pop music with vocals chorus and upbeat rhythm", "happy"),
    ("hip_hop_beat", "title: none | text: hip hop beat with rhythmic speech and heavy bass", "excited"),
    ("cinematic_orchestral", "title: none | text: cinematic orchestral music with strings and dramatic build", "attentive"),
    ("lofi_chill", "title: none | text: lo-fi chill music with vinyl crackle and relaxed beat", "relaxed"),
    ("folk_acoustic", "title: none | text: folk acoustic music with guitar and natural vocals", "happy"),
)

MUSIC_MOOD_BANK: tuple[AudioConceptEntry, ...] = (
    ("melancholic", "title: none | text: melancholic sad music with slow tempo and minor key", "relaxed"),
    ("energetic", "title: none | text: energetic upbeat music with fast tempo and major key", "excited"),
    ("tense", "title: none | text: tense suspenseful music with dissonant harmonies", "surprised"),
    ("calm", "title: none | text: calm peaceful music with soft dynamics and slow rhythm", "relaxed"),
    ("triumphant", "title: none | text: triumphant victorious music with brass and strong rhythm", "excited"),
)

SPEECH_STYLE_BANK: tuple[AudioConceptEntry, ...] = (
    ("quiet_speech", "title: none | text: quiet soft speech with low volume and slow pace", "attentive"),
    ("loud_speech", "title: none | text: loud energetic speech with high volume and fast pace", "excited"),
    ("whisper", "title: none | text: whispered speech barely audible and intimate", "attentive"),
    ("monologue", "title: none | text: a speaker delivers a flowing monologue at a steady pace", "attentive"),
    ("dialogue", "title: none | text: back and forth dialogue between two or more people", "attentive"),
    ("singing", "title: none | text: singing with melodic vocal melody and lyrics", "happy"),
)

MUSIC_VOCAL_BANK: tuple[AudioConceptEntry, ...] = (
    ("lead_singing", ("title: none | text: a lead singer performs a melodic vocal line over music", "title: none | text: a prominent sung voice carries the melody of a song"), "happy"),
    ("wordless_vocal", ("title: none | text: a human voice sings sustained wordless vowel sounds in a musical phrase", "title: none | text: wordless singing blends with the instrumental music"), "relaxed"),
    ("choir_vocals", ("title: none | text: a group choir sings together over musical accompaniment", "title: none | text: layered backing singers harmonize with the music"), "happy"),
    ("rap_vocal", ("title: none | text: rhythmic rap vocals are performed over a musical beat", "title: none | text: a rapper delivers rhythmic words over bass and percussion"), "excited"),
)

MUSIC_DRUMS_BANK: tuple[AudioConceptEntry, ...] = (
    ("acoustic_drum_kit", ("title: none | text: an acoustic drum kit plays a steady musical beat", "title: none | text: kick drum, snare, and cymbals drive the rhythm"), "excited"),
    ("electronic_drum_machine", ("title: none | text: programmed electronic drums create a precise rhythmic beat", "title: none | text: a drum machine and synthetic percussion shape the music"), "excited"),
    ("orchestral_percussion", ("title: none | text: orchestral percussion such as timpani and cymbals accents the score", "title: none | text: percussion instruments punctuate a cinematic orchestral passage"), "surprised"),
    ("hand_percussion", ("title: none | text: hand percussion and small drums play a repeating musical rhythm", "title: none | text: congas, shakers, or hand drums accompany the music"), "happy"),
)

MUSIC_BASS_BANK: tuple[AudioConceptEntry, ...] = (
    ("bass_guitar", ("title: none | text: a bass guitar plays a repeating low musical line", "title: none | text: plucked electric bass supports the rhythm and harmony"), "relaxed"),
    ("synth_bass", ("title: none | text: a deep electronic synthesizer bass anchors the music", "title: none | text: pulsing synthetic sub-bass forms the low end of the track"), "excited"),
    ("acoustic_low_strings", ("title: none | text: low acoustic strings provide a resonant bass line", "title: none | text: cello or upright bass carries the low musical register"), "relaxed"),
)

MUSIC_ELECTRONIC_BANK: tuple[AudioConceptEntry, ...] = (
    ("synth_pad", ("title: none | text: sustained electronic synthesizer pads create a soft musical texture", "title: none | text: warm ambient synth chords fill the musical background"), "relaxed"),
    ("synth_lead", ("title: none | text: a bright electronic synthesizer lead plays the main melody", "title: none | text: a synthesizer performs a clear melodic line over the beat"), "excited"),
    ("synth_arpeggio", ("title: none | text: repeating electronic arpeggios form a rhythmic musical pattern", "title: none | text: sequenced synthesizer notes pulse in a repeating pattern"), "excited"),
    ("chiptune", ("title: none | text: bright retro video game chiptune tones play a melody", "title: none | text: an 8-bit electronic game soundtrack uses synthetic tones"), "happy"),
)

# ---------------------------------------------------------------------------
# Haku-style Compositional Scene, Character, Plot & Meme Vocabulary Banks
# Each entry: (key, english_russian_probe_prompt, russian_narrative_phrase)
# ---------------------------------------------------------------------------

SCENE_SUBJECT_BANK: tuple[tuple[str, str, str], ...] = (
    ("two_anime_girls", "title: none | text: two anime girl characters standing together in a scene", "две аниме-героини в кадре"),
    ("single_anime_character", "title: none | text: close-up of a single anime character face and upper body", "крупный план аниме-персонажа"),
    ("group_of_characters", "title: none | text: group of multiple characters talking or fighting in a scene", "группа персонажей в сцене"),
    ("meme_template_image", "title: none | text: internet meme image macro with funny reaction face or comparison panels", "мем-картинка с реакцией или визуальным сопоставлением"),
    ("code_and_terminal_ui", "title: none | text: dark IDE workspace with source code editor sidebar and terminal logs", "рабочее окно IDE/терминала с кодом и логами"),
    ("vrm_companion_avatar", "title: none | text: 3D anime VRM companion girl avatar in dark HUD interface", "3D-аватар компаньона в интерфейсе"),
    ("game_warrior_monster", "title: none | text: video game warrior character fighting a monster or boss", "игровой персонаж в бою с противником/монстром"),
    ("web_article_feed", "title: none | text: web page feed with cards thumbnails and text articles", "веб-страница с карточками и лентой контента"),
    ("couple_man_woman", "title: none | text: a man and a woman standing or talking together in a romantic or friendly scene", "пара мужчина и женщина вместе"),
    ("lone_silhouette_character", "title: none | text: lone silhouette of a person against a dramatic background", "одинокий силуэт персонажа на фоне"),
    ("animal_or_creature", "title: none | text: animal or fantasy creature such as a cat dog bird dragon or monster close-up", "животное или фантастическое существо"),
    ("robot_or_mech", "title: none | text: robot android or giant mech suit standing in a scene", "робот / андроид / мех"),
    ("vehicle_or_spaceship", "title: none | text: car motorcycle aircraft or spaceship prominently shown", "транспорт / машина / корабль"),
    ("food_or_drink", "title: none | text: close-up of food dish drink coffee or meal on a table", "еда или напиток крупным планом"),
    ("landscape_no_characters", "title: none | text: pure landscape scenery without people such as mountains forest or ocean", "пейзаж без персонажей"),
    ("document_or_spreadsheet", "title: none | text: text document spreadsheet table or PDF page filling the screen", "документ / таблица / PDF"),
    ("social_media_feed", "title: none | text: social media feed with posts photos avatars and like buttons", "лента соцсети с постами и аватарами"),
    ("streamer_facecam", "title: none | text: streamer webcam facecam overlay on top of gameplay or desktop", "веб-камера стримера поверх игры или рабочего стола"),
)

CHARACTER_TRAIT_BANK: tuple[tuple[str, str, str], ...] = (
    ("yellow_coat_black_braid_purple_hair", "title: none | text: girl in yellow coat with black braid and girl with purple hair from behind", "одна героиня в жёлтом пальто с чёрной косой, рядом девушка с фиолетовыми волосами спиной к камере"),
    ("dark_fantasy_armor_cloak", "title: none | text: character wearing dark fantasy armor cloak and weapon", "персонаж в тёмном плаще/доспехах"),
    ("bright_colorful_anime_outfit", "title: none | text: anime character with bright colorful hair and stylized outfit", "персонаж с яркими волосами в стилизованном костюме"),
    ("casual_modern_clothes", "title: none | text: person or character in casual modern clothes shirt or jacket", "персонаж в современной повседневной одежде"),
    ("expressive_meme_face", "title: none | text: exaggerated funny or shocked facial expression in a meme", "выразительная мимика/реакция лица"),
    ("no_characters_text_ui", "title: none | text: pure software interface text panels and code without human characters", "чистый программный интерфейс без персонажей"),
    ("silver_white_hair", "title: none | text: character with silver white or platinum long hair", "персонаж с серебристыми/белыми волосами"),
    ("red_hair", "title: none | text: character with bright red or ginger hair", "персонаж с рыжими/красными волосами"),
    ("blue_hair", "title: none | text: character with blue or cyan hair", "персонаж с синими/голубыми волосами"),
    ("school_uniform", "title: none | text: character wearing a school uniform with skirt or blazer", "персонаж в школьной форме"),
    ("business_suit", "title: none | text: person wearing a formal business suit and tie", "персонаж в деловом костюме"),
    ("hoodie_casual", "title: none | text: person wearing a hoodie or casual streetwear", "персонаж в худи/уличной одежде"),
    ("armor_and_weapon", "title: none | text: character in armor holding a sword spear or other weapon", "персонаж в доспехах с оружием"),
    ("kimono_traditional", "title: none | text: character wearing a kimono or traditional East Asian clothing", "персонаж в кимоно/традиционной одежде"),
    ("cyberpunk_neon_outfit", "title: none | text: character in cyberpunk neon outfit with tech accessories", "персонаж в киберпанк-образе с неоном"),
    ("mask_or_helmet", "title: none | text: character wearing a mask helmet or visor covering the face", "персонаж в маске/шлеме"),
    ("glasses", "title: none | text: character wearing glasses or sunglasses", "персонаж в очках"),
    ("smiling_face", "title: none | text: character with a happy smiling face expression", "улыбающееся лицо"),
    ("angry_face", "title: none | text: character with an angry furious facial expression", "злое/раздражённое лицо"),
    ("crying_face", "title: none | text: character with a crying sad face with tears", "плачущее/грустное лицо"),
    ("shocked_face", "title: none | text: character with a shocked surprised wide-eyed expression", "шокированное/удивлённое лицо"),
    ("pointing_gesture", "title: none | text: character pointing a finger or hand toward something", "персонаж указывает рукой"),
    ("folded_arms", "title: none | text: character standing with folded crossed arms", "персонаж со скрещёнными руками"),
    ("running_pose", "title: none | text: character running or sprinting dynamically", "персонаж в беге"),
    ("sitting_pose", "title: none | text: character sitting on a chair or ground", "персонаж сидит"),
    ("lying_pose", "title: none | text: character lying down on a bed or ground", "персонаж лежит"),
)

SCENE_PLOT_ACTION_BANK: tuple[tuple[str, str, str], ...] = (
    ("standing_on_meadow_figure_hands_up", "title: none | text: characters standing on green meadow while a figure in the background raises hands up", "стоят на открытой местности, а на заднем плане фигура вскинула руки вверх"),
    ("intense_combat_magic_action", "title: none | text: dynamic combat fight scene with magic effects slashes or explosions", "идёт динамичное столкновение/экшен со спецэффектами"),
    ("dialogue_conversation_scene", "title: none | text: calm dialogue conversation between characters looking at each other", "спокойная сцена диалога между персонажами"),
    ("coding_debugging_agent_tasks", "title: none | text: developer and AI agent inspecting code files running tests and reading chat trajectory", "идёт работа с ИИ-агентом, чтение чата и проверка шагов выполнения задач в коде"),
    ("watching_youtube_with_sidebar", "title: none | text: watching a video on YouTube player with title likes and recommended videos on the right", "просмотр видеоролика в плеере YouTube с блоком рекомендаций справа"),
    ("meme_ironic_comparison_joke", "title: none | text: humorous meme contrasting two situations or showing an ironic punchline", "обыгрывается визуальная шутка / ироничное сравнение ситуаций"),
    ("kiss_romantic_scene", "title: none | text: two characters kissing or in a romantic intimate moment", "романтическая сцена поцелуя"),
    ("hugging_scene", "title: none | text: two characters hugging each other warmly", "персонажи обнимаются"),
    ("handshake_scene", "title: none | text: two people shaking hands in agreement or greeting", "рукопожатие при встрече или договоре"),
    ("sword_fight_scene", "title: none | text: characters fighting with swords blades or melee weapons", "бой на мечах/холодном оружии"),
    ("shooting_gun_scene", "title: none | text: character aiming or firing a gun or firearm", "стрельба из оружия"),
    ("magic_spell_cast_scene", "title: none | text: character casting a glowing magic spell or energy attack", "персонаж применяет магию/энергетическую атаку"),
    ("explosion_scene", "title: none | text: large explosion fire blast or shockwave in the scene", "взрыв/вспышка огня в кадре"),
    ("car_chase_scene", "title: none | text: cars chasing or driving fast through a street", "автомобильная погоня"),
    ("dancing_scene", "title: none | text: characters dancing together on a dance floor or stage", "персонажи танцуют"),
    ("singing_performance_scene", "title: none | text: singer performing a song on stage with a microphone", "вокальное выступление на сцене"),
    ("playing_instrument_scene", "title: none | text: person playing a musical instrument such as guitar piano or violin", "игра на музыкальном инструменте"),
    ("eating_food_scene", "title: none | text: person eating a meal or tasting food", "персонаж ест еду"),
    ("drinking_coffee_scene", "title: none | text: person drinking coffee tea or another beverage", "персонаж пьёт кофе/чай"),
    ("sleeping_scene", "title: none | text: person sleeping in bed or resting with eyes closed", "персонаж спит/отдыхает"),
    ("working_laptop_scene", "title: none | text: person working on a laptop at a desk", "работа за ноутбуком"),
    ("reading_book_scene", "title: none | text: person reading a book or document", "чтение книги/документа"),
    ("playing_video_game_scene", "title: none | text: person playing a video game with a controller or keyboard", "игра в видеоигру"),
    ("watching_tv_scene", "title: none | text: person watching television or a video on a screen", "просмотр телевизора/видео"),
    ("presenting_chart_scene", "title: none | text: person presenting a chart graph or slide deck to an audience", "презентация графика/слайдов"),
    ("typing_code_scene", "title: none | text: developer typing source code in an editor", "набор кода в редакторе"),
    ("debugging_error_scene", "title: none | text: developer inspecting an error traceback or failed test output", "разбор ошибки/трейсбека"),
    ("scrolling_feed_scene", "title: none | text: person scrolling a social media or news feed on screen", "прокрутка ленты новостей/соцсети"),
    ("video_call_scene", "title: none | text: person on a video call with other participants in a grid", "видеозвонок с участниками"),
)

SCENE_SETTING_BANK: tuple[tuple[str, str, str], ...] = (
    ("green_meadow_grass_trees_daylight", "title: none | text: sunny green grass meadow field with green trees and nature in the background", "на фоне зелёного луга, травы и деревьев при дневном свете"),
    ("dark_ide_sidebar_chat_layout", "title: none | text: dark grey and black IDE layout with workspace list on the left and chat in the center", "в тёмном интерфейсе с панелью воркспейсов слева и центральной лентой чата"),
    ("youtube_browser_page_layout", "title: none | text: web browser window with tabs at the top main video player and right sidebar", "в окне браузера с вкладками сверху, главным видеоплеером и правой колонкой"),
    ("dark_dungeon_or_night_street", "title: none | text: dark dungeon cave or night city street with shadows and glowing lights", "в тёмной локации / ночном окружении с контрастным светом"),
    ("indoor_room_or_office", "title: none | text: indoor room studio or office background with furniture", "внутри помещения / комнаты"),
    ("forest", "title: none | text: dense green forest with tall trees and foliage", "в густом лесу"),
    ("beach_ocean", "title: none | text: sandy beach with ocean waves and horizon", "на пляже у океана"),
    ("mountains", "title: none | text: mountain range peaks and rocky landscape", "в горах"),
    ("snow_landscape", "title: none | text: snowy winter landscape with snow covered ground", "на заснеженной местности"),
    ("rainy_street", "title: none | text: rainy city street with wet asphalt and reflections", "на дождливой улице"),
    ("cyberpunk_city", "title: none | text: futuristic cyberpunk city with neon signs and skyscrapers", "в киберпанк-городе с неоном"),
    ("medieval_castle", "title: none | text: medieval castle fortress or fantasy village", "в средневековом замке/деревне"),
    ("space_station", "title: none | text: space station spaceship interior or outer space with stars", "в космосе/на космической станции"),
    ("classroom", "title: none | text: school classroom with desks blackboard and students", "в школьном классе"),
    ("cafe_restaurant", "title: none | text: cozy cafe or restaurant interior with tables and warm light", "в кафе/ресторане"),
    ("bedroom", "title: none | text: cozy bedroom with a bed and soft lighting", "в спальне"),
    ("office_desk", "title: none | text: office desk with monitor keyboard documents and a chair", "за рабочим столом в офисе"),
    ("library", "title: none | text: library with tall bookshelves and reading tables", "в библиотеке"),
    ("laboratory", "title: none | text: science laboratory with equipment screens and benches", "в лаборатории"),
    ("stage_concert", "title: none | text: concert stage with spotlights speakers and a crowd", "на концертной сцене"),
    ("gym", "title: none | text: gym with workout equipment and mirrors", "в спортзале"),
    ("car_interior", "title: none | text: interior of a car with dashboard and steering wheel", "в салоне автомобиля"),
    ("train_station", "title: none | text: train station platform with trains and passengers", "на железнодорожной станции"),
    ("airport", "title: none | text: airport terminal with departure boards and travelers", "в аэропорту"),
    ("hospital", "title: none | text: hospital ward or clinic with medical equipment", "в больнице/клинике"),
)

MEME_AND_VIBE_BANK: tuple[tuple[str, str, str], ...] = (
    ("epic_fantasy_power_recap", "title: none | text: anime recap video about hunters monsters and overpowering skills", "атмосфера фэнтези-приключения/пересказа про охотников, монстров и прокачку способностей"),
    ("ironic_humor_meme_vibe", "title: none | text: funny ironic internet meme humor satire joke", "юмористический/мемный тон с иронией"),
    ("focused_engineering_workflow", "title: none | text: focused software engineering debugging and technical analysis", "сосредоточенная инженерная атмосфера разработки и анализа"),
    ("calm_cozy_slice_of_life", "title: none | text: calm cozy relaxing slice of life atmosphere", "спокойная и уютная атмосфера"),
    ("dramatic_tension_suspense", "title: none | text: dramatic tense suspenseful high stakes moment", "напряжённый драматичный момент"),
    ("wholesome_vibe", "title: none | text: wholesome heartwarming cute and kind atmosphere", "тёплая и добрая атмосфера"),
    ("cursed_image_vibe", "title: none | text: cursed bizarre unsettling surreal image", "странная/сюрреалистичная атмосфера"),
    ("deep_fried_meme", "title: none | text: deep fried heavily compressed oversaturated meme image", "пережатый «прожаренный» мем"),
    ("reaction_face_meme", "title: none | text: reaction face meme with a strong facial expression and caption", "мем с реакцией лица и подписью"),
    ("expectation_vs_reality", "title: none | text: expectation versus reality comparison meme with two panels", "мем «ожидание против реальности»"),
    ("nobody_literal_meme", "title: none | text: nobody literally meme format with a character doing something unprompted", "мем «никто: ...» с самодеятельным персонажем"),
    ("surprised_reaction", "title: none | text: surprised shocked reaction face meme", "мем с удивлённой реакцией"),
    ("this_is_fine", "title: none | text: this is fine dog sitting in fire meme", "мем «всё нормально» с персонажем в огне"),
    ("drake_format", "title: none | text: drake hotline bling approve disapprove two panel meme", "мем-шаблон с одобрением/неодобрением"),
    ("distracted_boyfriend", "title: none | text: distracted boyfriend looking at another person meme", "мем «отвлёкся на другого»"),
    ("galaxy_brain", "title: none | text: galaxy brain expanding brain meme with escalating ideas", "мем с расширяющимся сознанием"),
    ("two_buttons", "title: none | text: two buttons sweat drop choice meme", "мем с выбором из двух кнопок"),
    ("change_my_mind", "title: none | text: change my mind sign sitting at a table meme", "мем «переубеди меня»"),
    ("swole_doge", "title: none | text: swole doge vs cheems weak strong comparison meme", "мем с сильным и слабым псом"),
    ("cheems", "title: none | text: cheems dog with speech impediment meme", "мем с псом Чимсом"),
)

# ---------------------------------------------------------------------------
# DSP constants
# ---------------------------------------------------------------------------

_SR = 16000
_N_FFT = 512
_HOP = 160
_WIN = 320
_N_MELS = 128
_AUDIO_WINDOW_SECONDS = 2.0
_AUDIO_HOP_SECONDS = 1.0
_MAX_AUDIO_WINDOWS = 16
_AUDIO_DETAIL_BANKS = (
    "music_genre",
    "music_mood",
    "speech_style",
    "music_vocals",
    "music_drums",
    "music_bass",
    "music_electronic",
)

# Krumhansl-Schmuckler key profiles (major and minor)
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float64)
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float64)
_KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _build_mel_filterbank(sr: int, n_fft: int, n_mels: int, fmax: float) -> np.ndarray:
    mels = np.linspace(0.0, 2595.0 * math.log10(1.0 + fmax / 700.0), n_mels + 2)
    hz = 700.0 * (10.0 ** (mels / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(1, n_mels + 1):
        f0, f1, f2 = int(bins[m - 1]), int(bins[m]), int(bins[m + 1])
        for k in range(f0, f1):
            if f1 - f0 > 0:
                fb[m - 1, k] = (k - f0) / (f1 - f0)
        for k in range(f1, f2):
            if f2 - f1 > 0:
                fb[m - 1, k] = (f2 - k) / (f2 - f1)
    return fb


@dataclass
class DetailedObservation:
    """Multi-level sensory observation with rich detail."""
    modality: str  # "vision" | "audio" | "audio_visual" | "text"
    level0: str  # macro domain label
    level0_score: float
    level1: dict[str, Any] = field(default_factory=dict)  # facets
    level2: dict[str, Any] = field(default_factory=dict)  # grounded lexical
    level3: dict[str, Any] = field(default_factory=dict)  # temporal aggregation
    latency_ms: float = 0.0
    scene_similarity: float | None = None
    scene_changed: bool = False
    reflex_emotion: str = "neutral"
    description: str = ""
    raw_media_persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "level0": self.level0,
            "level0_score": round(self.level0_score, 4),
            "level1": self.level1,
            "level2": self.level2,
            "level3": self.level3,
            "latency_ms": round(self.latency_ms, 1),
            "scene_similarity": round(self.scene_similarity, 4) if self.scene_similarity is not None else None,
            "scene_changed": self.scene_changed,
            "reflex_emotion": self.reflex_emotion,
            "description": self.description,
            "raw_media_persisted": False,
        }


class DetailedSensoryDescriber:
    """Multi-level EG2-based sensory describer.

    Wraps EmbeddingGemmaSensoryCortex and adds:
    - Multi-head concept banks (styles, elements, genres, moods, speech styles)
    - NumPy DSP audio analysis (BPM, key/mode, spectral, speech modulation)
    - In-memory Windows OCR integration
    - 3-ring self-awareness perception snapshot
    - Detailed natural-language descriptions
    """

    def __init__(
        self,
        cortex: Any,
        *,
        scene_change_threshold: float = 0.88,
        ocr_provider: Any | None = None,
    ) -> None:
        self.cortex = cortex
        self.np = cortex._np
        self.scene_change_threshold = float(scene_change_threshold)
        self._last_screen_embedding: Any = None
        self._last_screen_level0: str | None = None
        self._mel_fb = _build_mel_filterbank(_SR, _N_FFT, _N_MELS, 8000.0)

        # Build multi-head concept banks from cortex text embeddings
        self._banks: dict[str, tuple[list[str], np.ndarray, dict[str, str]]] = {}
        self._build_banks()

        # Windows OCR state
        self._ocr_proc: subprocess.Popen | None = None
        self._ocr_ready = False
        self._ocr_lock = __import__("threading").Lock()
        self.ocr_provider = ocr_provider

    def _embed_text(self, text: str) -> np.ndarray:
        vec = np.asarray(self.cortex.embed_text(text), dtype=np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        return (vec / norm).astype(np.float32)

    def _build_bank(self, name: str, concepts: tuple[AudioConceptEntry, ...]) -> None:
        labels = [c[0] for c in concepts]
        emotions = {c[0]: c[2] for c in concepts}
        rows = []
        for concept in concepts:
            prompts = concept[1] if isinstance(concept[1], tuple) else (concept[1],)
            vectors = np.stack([self._embed_text(prompt) for prompt in prompts])
            prototype = vectors.mean(axis=0)
            prototype /= float(np.linalg.norm(prototype)) or 1.0
            rows.append(prototype)
        matrix = np.stack(rows).astype(np.float32)
        self._banks[name] = (labels, matrix, emotions)

    def _bank_definitions(self) -> dict[str, tuple[AudioConceptEntry, ...]]:
        return {
            "visual_style": VISUAL_STYLE_BANK,
            "visual_element": VISUAL_ELEMENT_BANK,
            "audio_scene": AUDIO_SCENE_BANK,
            "music_genre": MUSIC_GENRE_BANK,
            "music_mood": MUSIC_MOOD_BANK,
            "speech_style": SPEECH_STYLE_BANK,
            "music_vocals": MUSIC_VOCAL_BANK,
            "music_drums": MUSIC_DRUMS_BANK,
            "music_bass": MUSIC_BASS_BANK,
            "music_electronic": MUSIC_ELECTRONIC_BANK,
            "scene_subject": SCENE_SUBJECT_BANK,
            "character_trait": CHARACTER_TRAIT_BANK,
            "scene_plot_action": SCENE_PLOT_ACTION_BANK,
            "scene_setting": SCENE_SETTING_BANK,
            "meme_vibe": MEME_AND_VIBE_BANK,
        }

    def _build_banks(self) -> None:
        """Build all concept banks, reusing a validated `.npz` cache when possible.

        Embedding ~150 concepts takes about a second on CPU. The cache turns the
        next process start into a ~2 ms load; the signature covers every bank
        definition, the model root, and the exact text protocol, so editing a
        bank invalidates it automatically.
        """
        self._phrases = {}
        definitions = self._bank_definitions()
        model_root = Path(getattr(self.cortex, "model_root", DEFAULT_EG2_ONNX_ROOT))
        cache_path = model_root / "sensory_banks_v1.npz"
        signature = hashlib.sha256(
            repr((str(model_root), definitions)).encode("utf-8")
        ).hexdigest()
        cached: dict[str, np.ndarray] | None = None
        if cache_path.is_file():
            try:
                with np.load(cache_path, allow_pickle=False) as data:
                    if str(data["signature"].item()) == signature:
                        cached = {
                            name: np.asarray(data[name], dtype=np.float32)
                            for name in definitions
                            if name in data
                        }
            except Exception:  # noqa: BLE001 - a corrupt cache is just rebuilt
                cached = None

        for bank_name, bank_tuple in definitions.items():
            labels = [item[0] for item in bank_tuple]
            emotions = {item[0]: item[2] for item in bank_tuple}
            matrix = None
            if cached is not None:
                candidate = cached.get(bank_name)
                if candidate is not None and candidate.ndim == 2 and candidate.shape[0] == len(labels):
                    matrix = candidate
            if matrix is None:
                rows = []
                for item in bank_tuple:
                    prompts = item[1] if isinstance(item[1], tuple) else (item[1],)
                    vectors = np.stack([self._embed_text(prompt) for prompt in prompts])
                    prototype = vectors.mean(axis=0)
                    prototype /= float(np.linalg.norm(prototype)) or 1.0
                    rows.append(prototype)
                matrix = np.stack(rows).astype(np.float32)
            self._banks[bank_name] = (labels, matrix, emotions)
            self._phrases[bank_name] = {item[0]: item[2] for item in bank_tuple}

        if cached is None:
            try:
                np.savez_compressed(
                    cache_path,
                    signature=np.array(signature),
                    **{name: self._banks[name][1] for name in definitions},
                )
            except Exception:  # noqa: BLE001 - cache is best-effort
                pass

        # Reuse cortex's existing screen/audio banks
        self._banks["screen"] = (
            list(self.cortex._screen_labels),
            np.asarray(self.cortex._screen_matrix, dtype=np.float32),
            dict(self.cortex._screen_emotions),
        )
        self._banks["audio"] = (
            list(self.cortex._audio_labels),
            np.asarray(self.cortex._audio_matrix, dtype=np.float32),
            dict(self.cortex._audio_emotions),
        )

    def _classify(self, embedding: np.ndarray, bank_name: str) -> tuple[str, float, dict[str, float]]:
        """Classify an embedding against a concept bank. Returns (top_label, top_score, scores)."""
        labels, matrix, _ = self._banks[bank_name]
        scores_arr = matrix @ embedding
        scores = {labels[i]: float(scores_arr[i]) for i in range(len(labels))}
        top = max(scores, key=scores.get)
        return top, scores[top], scores

    def _mean_center(self, embedding: np.ndarray, bank_name: str) -> np.ndarray:
        """Mean-center cosine to suppress embedding anisotropy."""
        _, matrix, _ = self._banks[bank_name]
        mean_vec = matrix.mean(axis=0)
        centered = embedding - mean_vec
        norm = float(np.linalg.norm(centered)) or 1.0
        return (centered / norm).astype(np.float32)

    # -------------------------------------------------------------------
    # DSP audio analysis
    # -------------------------------------------------------------------

    def _pcm_to_float(self, pcm16_bytes: bytes, sample_rate: int) -> np.ndarray:
        pcm = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float64) / 32768.0
        if sample_rate != _SR and len(pcm) > 0:
            ratio = sample_rate / _SR
            idx = (np.arange(int(len(pcm) / ratio)) * ratio).astype(int)
            pcm = pcm[idx]
        return pcm

    def _rms_dbfs(self, pcm: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(pcm ** 2))) if len(pcm) > 0 else 0.0
        if rms <= 1e-10:
            return -100.0
        return round(20 * math.log10(rms), 1)

    def _spectral_centroid(self, pcm: np.ndarray) -> float:
        if len(pcm) < _N_FFT:
            return 0.0
        window = np.hanning(_N_FFT)
        frames = 1 + (len(pcm) - _N_FFT) // _HOP
        centroid = 0.0
        total = 0.0
        for i in range(frames):
            seg = pcm[i * _HOP : i * _HOP + _N_FFT] * window
            spec = np.abs(np.fft.rfft(seg, n=_N_FFT)) ** 2
            freqs = np.fft.rfftfreq(_N_FFT, 1.0 / _SR)
            centroid += float(np.sum(freqs * spec))
            total += float(np.sum(spec))
        if total <= 0:
            return 0.0
        return round(centroid / total, 1)

    def _onset_bpm(self, pcm: np.ndarray) -> tuple[float, float]:
        """Estimate BPM and pulse clarity via onset autocorrelation."""
        if len(pcm) < _SR:
            return 0.0, 0.0
        # Energy envelope
        win = 512
        hop = 256
        n_frames = 1 + (len(pcm) - win) // hop
        envelope = np.zeros(n_frames)
        for i in range(n_frames):
            seg = pcm[i * hop : i * hop + win]
            envelope[i] = float(np.sqrt(np.mean(seg ** 2)))
        # Onset strength (spectral flux approximation via envelope diff)
        onset = np.diff(envelope)
        onset = np.maximum(onset, 0.0)
        # Autocorrelation for BPM
        if len(onset) < 4:
            return 0.0, 0.0
        onset = onset - onset.mean()
        corr = np.correlate(onset, onset, mode="full")
        corr = corr[len(corr) // 2:]
        # Search 60-200 BPM
        min_lag = int(60.0 / 200.0 * (_SR / hop))
        max_lag = int(60.0 / 60.0 * (_SR / hop))
        if max_lag >= len(corr):
            max_lag = len(corr) - 1
        if min_lag >= max_lag:
            return 0.0, 0.0
        segment = corr[min_lag:max_lag + 1]
        peak_idx = int(np.argmax(segment)) + min_lag
        if peak_idx <= 0:
            return 0.0, 0.0
        bpm = 60.0 * (_SR / hop) / peak_idx
        # Pulse clarity: peak / mean (absolute value to avoid negative)
        clarity = abs(float(segment.max())) / (abs(float(segment.mean())) + 1e-10)
        clarity = min(1.0, clarity / 5.0)
        return round(bpm, 1), round(clarity, 3)

    def _key_mode(self, pcm: np.ndarray) -> tuple[str, str]:
        """Estimate key and mode (major/minor) via chroma + Krumhansl-Schmuckler."""
        if len(pcm) < _N_FFT:
            return "unknown", "unknown"
        # Compute chroma
        window = np.hanning(_N_FFT)
        frames = 1 + (len(pcm) - _N_FFT) // _HOP
        chroma = np.zeros(12)
        for i in range(frames):
            seg = pcm[i * _HOP : i * _HOP + _N_FFT] * window
            spec = np.abs(np.fft.rfft(seg, n=_N_FFT))
            freqs = np.fft.rfftfreq(_N_FFT, 1.0 / _SR)
            for f, s in zip(freqs, spec):
                if f < 20 or f > 5000:
                    continue
                midi = 12 * math.log2(f / 440.0) + 69
                pc = int(round(midi)) % 12
                chroma[pc] += s
        chroma = chroma / (float(np.linalg.norm(chroma)) + 1e-10)
        # Match against 12 rotations of major and minor profiles
        best_key = "C"
        best_mode = "major"
        best_corr = -1.0
        for shift in range(12):
            for mode, profile in (("major", _KS_MAJOR), ("minor", _KS_MINOR)):
                rotated = np.roll(profile, shift)
                rnorm = float(np.linalg.norm(rotated)) or 1.0
                corr = float(np.dot(chroma, rotated / rnorm))
                if corr > best_corr:
                    best_corr = corr
                    best_key = _KEY_NAMES[shift]
                    best_mode = mode
        return best_key, best_mode

    def _speech_modulation(self, pcm: np.ndarray) -> float:
        """Estimate speech syllable rate (3-7 Hz modulation)."""
        if len(pcm) < _SR:
            return 0.0
        win = 256
        hop = 128
        n_frames = 1 + (len(pcm) - win) // hop
        envelope = np.zeros(n_frames)
        for i in range(n_frames):
            seg = pcm[i * hop : i * hop + win]
            envelope[i] = float(np.sqrt(np.mean(seg ** 2)))
        # Band-pass around 3-7 Hz via FFT
        env_fft = np.abs(np.fft.rfft(envelope - envelope.mean()))
        freqs = np.fft.rfftfreq(len(envelope), 1.0 / (_SR / hop))
        mask = (freqs >= 2.0) & (freqs <= 8.0)
        if not mask.any():
            return 0.0
        energy = float(np.sum(env_fft[mask] ** 2))
        total = float(np.sum(env_fft ** 2)) + 1e-10
        return round(energy / total, 3)

    def _spectral_balance(self, pcm: np.ndarray) -> dict[str, float]:
        """Return sub-bass / mid / high energy ratios."""
        if len(pcm) < _N_FFT:
            return {"sub_bass": 0.0, "mid": 0.0, "high": 0.0}
        window = np.hanning(_N_FFT)
        frames = 1 + (len(pcm) - _N_FFT) // _HOP
        bands = np.zeros(3)
        for i in range(frames):
            seg = pcm[i * _HOP : i * _HOP + _N_FFT] * window
            spec = np.abs(np.fft.rfft(seg, n=_N_FFT)) ** 2
            freqs = np.fft.rfftfreq(_N_FFT, 1.0 / _SR)
            bands[0] += float(np.sum(spec[freqs < 250]))
            bands[1] += float(np.sum(spec[(freqs >= 250) & (freqs < 2000)]))
            bands[2] += float(np.sum(spec[freqs >= 2000]))
        total = float(np.sum(bands)) + 1e-10
        return {
            "sub_bass": round(float(bands[0] / total), 3),
            "mid": round(float(bands[1] / total), 3),
            "high": round(float(bands[2] / total), 3),
        }

    def analyze_audio_dsp(self, pcm16_bytes: bytes, sample_rate: int = 16000) -> dict[str, Any]:
        """Run full DSP audio analysis. Returns metrics dict."""
        pcm = self._pcm_to_float(pcm16_bytes, sample_rate)
        if len(pcm) == 0:
            return {"error": "empty_audio"}
        bpm, clarity = self._onset_bpm(pcm)
        key, mode = self._key_mode(pcm)
        balance = self._spectral_balance(pcm)
        speech_mod = self._speech_modulation(pcm)
        rms = self._rms_dbfs(pcm)
        centroid = self._spectral_centroid(pcm)
        duration = round(len(pcm) / _SR, 2)
        return {
            "duration_s": duration,
            "rms_dbfs": rms,
            "spectral_centroid_hz": centroid,
            "bpm": bpm,
            "pulse_clarity": clarity,
            "key": key,
            "mode": mode,
            "spectral_balance": balance,
            "speech_modulation": speech_mod,
            "is_speech_likely": speech_mod > 0.15,
            "is_music_likely": clarity > 0.3 and bpm > 60,
        }

    def _audio_window_slices(
        self, pcm16_bytes: bytes, sample_rate: int
    ) -> list[tuple[float, float, bytes]]:
        """Split mono PCM into bounded overlapping windows for temporal detail."""
        np = self.np
        samples = np.frombuffer(pcm16_bytes, dtype=np.int16)
        if not samples.size:
            return []
        window_size = max(1, round(sample_rate * _AUDIO_WINDOW_SECONDS))
        hop_size = max(1, round(sample_rate * _AUDIO_HOP_SECONDS))
        if samples.size <= window_size:
            starts = [0]
        else:
            starts = list(range(0, samples.size - window_size + 1, hop_size))
            final_start = samples.size - window_size
            if starts[-1] != final_start:
                starts.append(final_start)
        if len(starts) > _MAX_AUDIO_WINDOWS:
            indices = np.linspace(0, len(starts) - 1, _MAX_AUDIO_WINDOWS).round().astype(int)
            starts = [starts[int(index)] for index in indices]
        return [
            (
                round(start / sample_rate, 3),
                round(min(samples.size, start + window_size) / sample_rate, 3),
                samples[start : start + window_size].tobytes(),
            )
            for start in starts
        ]

    @staticmethod
    def _rank_audio_scores(scores: dict[str, float], *, limit: int = 3) -> list[dict[str, Any]]:
        return [
            {"label": label, "similarity": round(float(score), 4), "verified": False}
            for label, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    # -------------------------------------------------------------------
    # Windows OCR integration (in-memory, no disk)
    # -------------------------------------------------------------------

    def _start_ocr_pipe(self) -> None:
        """Start persistent PowerShell WinRT OCR pipe if not already running."""
        with self._ocr_lock:
            if self._ocr_proc is not None and self._ocr_proc.poll() is None:
                return
            ps_code = r'''
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod })[0]
function Await($op, $type) {
    $m = $asTask.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.GetAwaiter().GetResult()
}
$engRu = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('ru')))
$engEn = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('en-US')))
Write-Output 'READY'
while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ($line -eq 'QUIT') { break }
    try {
        $bytes = [Convert]::FromBase64String($line)
        $ras = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $dw = New-Object Windows.Storage.Streams.DataWriter($ras.GetOutputStreamAt(0))
        $dw.WriteBytes($bytes)
        $null = Await ($dw.StoreAsync()) ([uint32])
        $ras.Seek(0)
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $sbmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $w = $sbmp.PixelWidth
        $h = $sbmp.PixelHeight
        $linesRu = @()
        if ($null -ne $engRu) {
            $r = Await ($engRu.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
            foreach ($l in $r.Lines) {
                $w0 = @($l.Words)[0]
                $rect = $w0.BoundingRect
                $linesRu += @{ text = $l.Text; x = [int]$rect.X; y = [int]$rect.Y }
            }
        }
        $linesEn = @()
        if ($null -ne $engEn) {
            $r2 = Await ($engEn.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])
            foreach ($l in $r2.Lines) {
                $w0 = @($l.Words)[0]
                $rect = $w0.BoundingRect
                $linesEn += @{ text = $l.Text; x = [int]$rect.X; y = [int]$rect.Y }
            }
        }
        $out = @{ ok = $true; width = $w; height = $h; ru = $linesRu; en = $linesEn } | ConvertTo-Json -Compress -Depth 4
        Write-Output $out
    } catch {
        Write-Output (@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress)
    }
}
'''
            self._ocr_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_code],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            ready = self._ocr_proc.stdout.readline().strip()
            if ready == "READY":
                self._ocr_ready = True
            else:
                self._ocr_proc = None
                self._ocr_ready = False

    def _ocr_image_bytes(self, image_bytes: bytes, *, upscale: bool = True) -> list[dict[str, Any]]:
        """Run in-memory OCR on image bytes. Returns list of {text, x, y, lang}."""
        if self.ocr_provider is not None:
            try:
                return self.ocr_provider(image_bytes)
            except Exception:
                return []
        self._start_ocr_pipe()
        if not self._ocr_ready or self._ocr_proc is None:
            return []
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            if upscale and img.width < 1600:
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.BICUBIC)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            b64 = __import__("base64").b64encode(buf.getvalue()).decode("ascii")
            self._ocr_proc.stdin.write(b64 + "\n")
            self._ocr_proc.stdin.flush()
            resp = self._ocr_proc.stdout.readline().strip()
            data = json.loads(resp)
            if not data.get("ok"):
                return []
            results: list[dict[str, Any]] = []
            for item in data.get("ru", []):
                results.append({"text": item["text"], "x": item["x"], "y": item["y"], "lang": "ru"})
            for item in data.get("en", []):
                results.append({"text": item["text"], "x": item["x"], "y": item["y"], "lang": "en"})
            return results
        except Exception:
            return []

    def _filter_ocr_text(self, ocr_items: list[dict[str, Any]]) -> str:
        """Filter OCR text: remove garbage, deduplicate similar, keep meaningful."""
        seen: set[str] = set()
        texts: list[str] = []
        for item in ocr_items:
            t = item["text"].strip()
            if not t or len(t) < 2:
                continue
            # Skip pure symbols/numbers without letters
            if not any(c.isalpha() for c in t):
                continue
            # Skip very short tokens that are likely OCR noise
            if len(t) <= 2 and not t.isalnum():
                continue
            # Deduplicate exact matches
            if t in seen:
                continue
            # Deduplicate near-duplicates (one contains the other)
            is_dup = False
            for existing in texts:
                if t in existing or existing in t:
                    is_dup = True
                    break
            if is_dup:
                continue
            seen.add(t)
            texts.append(t)
        # Sort by length (longer first) to prioritize meaningful text
        texts.sort(key=len, reverse=True)
        return " | ".join(texts[:15])

    def _ocr_text_string(self, image_bytes: bytes) -> str:
        """Return all OCR text joined into a single string."""
        items = self._ocr_image_bytes(image_bytes)
        return self._filter_ocr_text(items)

    # -------------------------------------------------------------------
    # Multi-level visual description
    # -------------------------------------------------------------------

    def _embed_image_and_tokens(self, image_bytes: bytes) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
        """Single-pass image embedding + 70 spatial tokens + main canvas crop embedding."""
        from PIL import Image
        try:
            if getattr(self.cortex, "vision_session", None) is None:
                emb = np.asarray(self.cortex.embed_image_bytes(image_bytes), dtype=np.float32)
                return emb, None, emb
            raw_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            gh, gw = 21, 30
            def _run_pil(pil_img):
                img = pil_img.resize((gw * 16, gh * 16))
                arr = np.asarray(img, dtype=np.float32) / 255.0
                patches = arr.reshape(gh, 16, gw, 16, 3).transpose(0, 2, 1, 3, 4).reshape(1, gh * gw, 768)
                pos_y, pos_x = np.meshgrid(np.arange(gh), np.arange(gw), indexing="ij")
                pixel_pos = np.stack([pos_x.ravel(), pos_y.ravel()], axis=-1)[None, :, :].astype(np.int64)
                vf = self.cortex.vision_session.run(
                    ["image_features"],
                    {"pixel_values": patches, "pixel_position_ids": pixel_pos},
                )[0]
                ids = np.array([[2, 255999] + [258880] * vf.shape[0] + [258882, 1]], dtype=np.int64)
                lhs, se = self.cortex.text_session.run(
                    ["last_hidden_state", "sentence_embedding"],
                    {
                        "input_ids": ids,
                        "attention_mask": np.ones_like(ids),
                        "image_features": vf,
                        "video_features": self.cortex._empty,
                        "audio_features": self.cortex._empty,
                    },
                )
                se_vec = se[0] / (np.linalg.norm(se[0]) + 1e-10)
                tok_vecs = lhs[0, 2 : 2 + vf.shape[0], :]
                tok_vecs = tok_vecs / (np.linalg.norm(tok_vecs, axis=1, keepdims=True) + 1e-10)
                return se_vec.astype(np.float32), tok_vecs.astype(np.float32)

            full_emb, full_tokens = _run_pil(raw_img)
            w, h = raw_img.size
            if w >= 400 and h >= 260:
                crop_img = raw_img.crop((int(w * 0.03), int(h * 0.08), int(w * 0.74), int(h * 0.84)))
                crop_emb, _ = _run_pil(crop_img)
            else:
                crop_emb = full_emb
            return full_emb, full_tokens, crop_emb
        except Exception:
            emb = np.asarray(self.cortex.embed_image_bytes(image_bytes), dtype=np.float32)
            return emb, None, emb

    def _visual_zones_from_tokens(self, full_emb: np.ndarray, tok_vecs: np.ndarray | None) -> dict[str, str]:
        """Classify 5 spatial zones directly from the 7x10 (70) contextualized tokens."""
        if tok_vecs is None or tok_vecs.shape[0] < 70:
            top, score, _ = self._classify(full_emb, "visual_element")
            return {z: f"{top} ({score:.2f})" for z in ("top", "bottom", "left", "center", "right")}
        grid = tok_vecs[:70].reshape(7, 10, -1)
        zone_slices = {
            "top": grid[:2, :, :].reshape(-1, 768),
            "bottom": grid[5:, :, :].reshape(-1, 768),
            "left": grid[:, :3, :].reshape(-1, 768),
            "center": grid[1:6, 2:8, :].reshape(-1, 768),
            "right": grid[:, 7:, :].reshape(-1, 768),
        }
        zones: dict[str, str] = {}
        for z_name, z_tokens in zone_slices.items():
            z_vec = 0.65 * z_tokens.mean(axis=0) + 0.35 * full_emb
            z_vec = (z_vec / (np.linalg.norm(z_vec) + 1e-10)).astype(np.float32)
            top, score, _ = self._classify(z_vec, "visual_element")
            zones[z_name] = f"{top} ({score:.2f})"
        return zones

    def describe_screen_detailed(self, image_bytes: bytes, *, prompt: str = "") -> DetailedObservation:
        """Detailed multi-level screen & plot description replacing VLM."""
        np = self.np
        t0 = time.perf_counter()

        emb, tok_vecs, crop_emb = self._embed_image_and_tokens(image_bytes)
        blended_emb = (0.55 * emb + 0.45 * crop_emb)
        blended_emb = (blended_emb / (np.linalg.norm(blended_emb) + 1e-10)).astype(np.float32)

        # L0: macro domain
        screen_top, screen_score, screen_scores = self._classify(emb, "screen")

        # L1: style, element, and Haku-style compositional plot/scene banks
        style_top, style_score, style_scores = self._classify(emb, "visual_style")
        element_top, element_score, element_scores = self._classify(emb, "visual_element")
        subj_top, subj_score, _ = self._classify(blended_emb, "scene_subject")
        trait_top, trait_score, _ = self._classify(crop_emb, "character_trait")
        action_top, action_score, _ = self._classify(blended_emb, "scene_plot_action")
        setting_top, setting_score, _ = self._classify(blended_emb, "scene_setting")
        vibe_top, vibe_score, _ = self._classify(blended_emb, "meme_vibe")

        # Scene change
        scene_sim = None
        changed = True
        if self._last_screen_embedding is not None:
            scene_sim = float(np.dot(self._last_screen_embedding, emb))
            changed = scene_sim < self.scene_change_threshold
        self._last_screen_embedding = emb

        # L2: OCR text (filtered, deduplicated)
        ocr_items = self._ocr_image_bytes(image_bytes)
        ocr_text = self._filter_ocr_text(ocr_items)

        # Spatial zones from 70 contextualized tokens
        zones = self._visual_zones_from_tokens(emb, tok_vecs)

        # Compose rich narrative description. Only clauses with a confident
        # top-1 score are spoken/recorded; weak guesses stay out so the
        # companion never invents a plot element.
        def _phrase(bank: str, label: str, score: float, threshold: float) -> str:
            if score < threshold:
                return ""
            return self._phrases.get(bank, {}).get(label, label)

        subj_phrase = _phrase("scene_subject", subj_top, subj_score, 0.62)
        trait_phrase = _phrase("character_trait", trait_top, trait_score, 0.62)
        action_phrase = _phrase("scene_plot_action", action_top, action_score, 0.62)
        setting_phrase = _phrase("scene_setting", setting_top, setting_score, 0.62)
        vibe_phrase = _phrase("meme_vibe", vibe_top, vibe_score, 0.60)

        clauses: list[str] = []
        if subj_phrase:
            clauses.append(subj_phrase)
        if trait_phrase:
            clauses.append(trait_phrase)
        if action_phrase:
            clauses.append(action_phrase)
        if setting_phrase:
            clauses.append(setting_phrase)
        if vibe_phrase:
            clauses.append(vibe_phrase)
        narrative = "Сюжет кадра: " + ", ".join(clauses) if clauses else "Сюжет кадра: детали не определены"

        desc_parts = [
            f"Экран: {screen_top} ({screen_score:.2f})",
            narrative,
            f"Стиль: {style_top} ({style_score:.2f})",
            f"Элемент: {element_top} ({element_score:.2f})",
        ]
        if ocr_text:
            desc_parts.append(f"Текст на экране: {ocr_text[:500]}")
        if zones:
            zone_str = ", ".join(f"{k}={v}" for k, v in zones.items())
            desc_parts.append(f"Зоны: {zone_str}")

        reflex_emotion = self.cortex._screen_emotions.get(screen_top, "neutral")

        obs = DetailedObservation(
            modality="vision",
            level0=screen_top,
            level0_score=screen_score,
            level1={
                "style": style_top,
                "style_score": round(style_score, 4),
                "element": element_top,
                "element_score": round(element_score, 4),
                "subject": subj_top,
                "subject_score": round(subj_score, 4),
                "character_trait": trait_top,
                "character_trait_score": round(trait_score, 4),
                "plot_action": action_top,
                "plot_action_score": round(action_score, 4),
                "setting": setting_top,
                "setting_score": round(setting_score, 4),
                "meme_vibe": vibe_top,
                "meme_vibe_score": round(vibe_score, 4),
                "narrative": narrative,
                "zones": zones,
                "all_screen_scores": {k: round(v, 4) for k, v in screen_scores.items()},
                "all_style_scores": {k: round(v, 4) for k, v in style_scores.items()},
            },
            level2={
                "ocr_text": ocr_text[:1000],
                "ocr_items": ocr_items[:20],
                "ocr_count": len(ocr_items),
            },
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            scene_similarity=scene_sim,
            scene_changed=changed,
            reflex_emotion=reflex_emotion,
            description="; ".join(desc_parts),
        )
        return obs

    def describe_displays_detailed(
        self, image_bytes_list: list[bytes], *, audio_wav_bytes: bytes | None = None
    ) -> str:
        """Detailed multi-display description with OCR and audio."""
        parts = []
        for index, img_bytes in enumerate(image_bytes_list or [], start=1):
            try:
                obs = self.describe_screen_detailed(img_bytes)
                parts.append(f"Дисплей {index}: {obs.description}")
            except Exception as exc:
                parts.append(f"Дисплей {index}: ошибка ({str(exc)[:80]})")

        if audio_wav_bytes:
            try:
                audio_obs = self.describe_audio_detailed(audio_wav_bytes)
                parts.append(f"Звук: {audio_obs.description}")
            except Exception as exc:
                parts.append(f"Звук: ошибка ({str(exc)[:80]})")

        return "; ".join(parts)

    # -------------------------------------------------------------------
    # Multi-level audio description
    # -------------------------------------------------------------------

    def describe_audio_detailed(
        self, wav_bytes: bytes, *, temporal_detail: bool = True
    ) -> DetailedObservation:
        """Classify a broad scene and optionally refine overlapping windows.

        ``temporal_detail=False`` is the live path: it embeds the whole bounded
        clip once, then derives scene and specialist rankings from that shared
        representation. The full overlapping-window pass remains available for
        offline inspection where per-window transitions justify its CPU cost.
        """
        np = self.np
        t0 = time.perf_counter()

        # Parse WAV
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            sr = w.getframerate()
            pcm_raw = w.readframes(w.getnframes())
            channels = w.getnchannels()
            sample_width = w.getsampwidth()

        if sample_width != 2 or channels < 1 or sr < 1:
            raise ValueError("audio description expects PCM16 WAV with a valid sample rate")
        interleaved = np.frombuffer(pcm_raw, dtype=np.int16)
        if interleaved.size % channels:
            raise ValueError("PCM frame count is not divisible by the channel count")
        if channels > 1:
            mono = np.clip(
                np.rint(interleaved.reshape(-1, channels).astype(np.float32).mean(axis=1)),
                -32768,
                32767,
            ).astype(np.int16)
            pcm_raw = mono.tobytes()

        # DSP analysis
        dsp = self.analyze_audio_dsp(pcm_raw, sample_rate=sr)

        # Embedding stage is timed separately from semantic ranking for the next
        # live acceptance run. Capture time belongs to the upstream audio source.
        embedding_ms = 0.0
        embedding_started = time.perf_counter()
        emb = self.cortex.embed_audio_pcm16(pcm_raw, sample_rate=sr)
        embedding_ms += (time.perf_counter() - embedding_started) * 1000.0

        # L1: broad positive scene hypotheses. Similarities are rankings, not
        # calibrated probabilities, and no single absent-music prompt competes.
        l1_started = time.perf_counter()
        _, _, scene_scores = self._classify(emb, "audio_scene")
        audio_active = float(dsp.get("rms_dbfs", -160.0)) > -95.0
        scene_ranked = (
            self._rank_audio_scores(scene_scores, limit=len(scene_scores))
            if audio_active else []
        )
        scene_top = scene_ranked[0]["label"] if scene_ranked else "unknown_audio"
        scene_score = float(scene_scores.get(scene_top, 0.0))
        l1_ms = (time.perf_counter() - l1_started) * 1000.0

        # L2: every non-silent window gets independent specialist hypotheses.
        # Vocal, drum, bass, and electronic heads are not gated by one music bit.
        l2_started = time.perf_counter()
        window_embedding_ms = 0.0
        windows = (
            self._audio_window_slices(pcm_raw, sr)
            if temporal_detail
            else [(0.0, round(len(pcm_raw) / 2 / sr, 3), pcm_raw)]
        )
        window_features: list[dict[str, Any]] = []
        window_scene_vectors: list[np.ndarray] = []
        all_window_scores: dict[str, list[dict[str, float]]] = {
            bank: [] for bank in _AUDIO_DETAIL_BANKS
        }
        all_scene_scores: list[dict[str, float]] = []
        for index, (start_s, end_s, window_pcm) in enumerate(windows):
            window_dsp = self.analyze_audio_dsp(window_pcm, sample_rate=sr)
            if index == 0 and len(windows) == 1:
                window_emb = emb
            else:
                window_embed_started = time.perf_counter()
                window_emb = self.cortex.embed_audio_pcm16(window_pcm, sample_rate=sr)
                elapsed_window_embedding_ms = (time.perf_counter() - window_embed_started) * 1000.0
                embedding_ms += elapsed_window_embedding_ms
                window_embedding_ms += elapsed_window_embedding_ms
            energy_dbfs = float(window_dsp.get("rms_dbfs", -160.0))
            if energy_dbfs <= -95.0:
                local_scene_scores: dict[str, float] = {}
                local_specialist_scores = {bank: {} for bank in _AUDIO_DETAIL_BANKS}
                local_scene = "unknown_audio"
            else:
                _, _, local_scene_scores = self._classify(window_emb, "audio_scene")
                local_scene = max(local_scene_scores, key=local_scene_scores.get)
                local_specialist_scores = {
                    bank: self._classify(window_emb, bank)[2]
                    for bank in _AUDIO_DETAIL_BANKS
                }
            all_scene_scores.append(local_scene_scores)
            for bank, scores in local_specialist_scores.items():
                all_window_scores[bank].append(scores)
            window_scene_vectors.append(np.asarray(window_emb, dtype=np.float32))
            window_features.append({
                "start_s": start_s,
                "end_s": end_s,
                "scene_candidate": {
                    "label": local_scene,
                    "similarity": round(float(local_scene_scores.get(local_scene, 0.0)), 4),
                    "verified": False,
                },
                "specialist_candidates": {
                    bank: self._rank_audio_scores(scores, limit=3)
                    for bank, scores in local_specialist_scores.items()
                },
                "signal_features": {
                    "rms_dbfs": round(energy_dbfs, 2),
                    "bpm": window_dsp.get("bpm"),
                    "pulse_clarity": window_dsp.get("pulse_clarity"),
                    "speech_modulation": window_dsp.get("speech_modulation"),
                    "spectral_balance": window_dsp.get("spectral_balance", {}),
                },
            })

        # Keep embedding work in its own bucket even though window embeddings
        # are requested while L2 walks the windows.
        l2_ms = max(
            0.0,
            (time.perf_counter() - l2_started) * 1000.0 - window_embedding_ms,
        )
        context_concepts = scene_ranked[:3]
        specialist_candidates: dict[str, list[dict[str, Any]]] = {}
        for bank, per_window in all_window_scores.items():
            labels = self._banks[bank][0]
            median_scores = {
                label: float(np.median([scores[label] for scores in per_window if label in scores]))
                for label in labels
                if any(label in scores for scores in per_window)
            }
            specialist_candidates[bank] = self._rank_audio_scores(median_scores, limit=3)

        # Record changes separately from per-window characteristics.
        window_changes: list[dict[str, Any]] = []
        for previous, current, previous_scores, current_scores, previous_vec, current_vec in zip(
            window_features,
            window_features[1:],
            all_scene_scores,
            all_scene_scores[1:],
            window_scene_vectors,
            window_scene_vectors[1:],
        ):
            previous_scene = previous["scene_candidate"]["label"]
            current_scene = current["scene_candidate"]["label"]
            prev_signal = previous["signal_features"]
            curr_signal = current["signal_features"]
            specialist_changes = {}
            for bank in _AUDIO_DETAIL_BANKS:
                prev_top = previous["specialist_candidates"][bank]
                curr_top = current["specialist_candidates"][bank]
                prev_label = prev_top[0]["label"] if prev_top else None
                curr_label = curr_top[0]["label"] if curr_top else None
                specialist_changes[bank] = {
                    "from": prev_label,
                    "to": curr_label,
                    "changed": prev_label != curr_label,
                }
            previous_bpm = prev_signal.get("bpm")
            current_bpm = curr_signal.get("bpm")
            window_changes.append({
                "from_start_s": previous["start_s"],
                "to_start_s": current["start_s"],
                "scene_candidate_changed": previous_scene != current_scene,
                "scene_embedding_similarity": round(float(np.dot(previous_vec, current_vec)), 4),
                "scene_score_delta": round(
                    float(current_scores.get(current_scene, 0.0) - previous_scores.get(previous_scene, 0.0)),
                    4,
                ),
                "rms_delta_db": round(float(curr_signal["rms_dbfs"] - prev_signal["rms_dbfs"]), 2),
                "bpm_delta": (
                    round(float(current_bpm - previous_bpm), 2)
                    if isinstance(current_bpm, (int, float)) and isinstance(previous_bpm, (int, float))
                    else None
                ),
                "specialist_candidate_changes": specialist_changes,
            })

        # L3: aggregate candidates and support across adjacent windows.
        l3_started = time.perf_counter()
        scene_medians = {
            label: float(np.median([scores[label] for scores in all_scene_scores if label in scores]))
            for label in self._banks["audio_scene"][0]
            if any(label in scores for scores in all_scene_scores)
        }
        scene_summary = self._rank_audio_scores(scene_medians, limit=4)
        feature_support: dict[str, dict[str, int]] = {}
        for bank in _AUDIO_DETAIL_BANKS:
            support: dict[str, int] = {}
            for item in window_features:
                candidates = item["specialist_candidates"].get(bank, [])
                if candidates:
                    label = candidates[0]["label"]
                    support[label] = support.get(label, 0) + 1
            feature_support[bank] = support
        l3_ms = (time.perf_counter() - l3_started) * 1000.0

        obs = DetailedObservation(
            modality="audio",
            level0=scene_top,
            level0_score=scene_score,
            level1={
                "audio_scene": scene_top,
                "scene_similarity": round(scene_score, 4),
                "scene_candidates": scene_ranked,
                "calibrated": False,
            },
            level2={
                "dsp": dsp,
                "duration_s": dsp.get("duration_s", 0),
                "rms_dbfs": dsp.get("rms_dbfs", 0),
                "spectral_centroid_hz": dsp.get("spectral_centroid_hz", 0),
                "context_concepts": context_concepts,
                "specialist_candidates": specialist_candidates,
                "window_features": window_features,
                "window_changes": window_changes,
                "calibrated": False,
            },
            level3={
                "temporal_summary": {
                    "scene_candidates": scene_summary,
                    "feature_top_window_support": feature_support,
                    "window_count": len(window_features),
                    "scene_change_count": sum(
                        1 for item in window_changes if item["scene_candidate_changed"]
                    ),
                    "window_changes": window_changes,
                },
                "stage_latency_ms": {
                    "capture": None,
                    "embedding": round(embedding_ms, 2),
                    "L1": round(l1_ms, 2),
                    "L2": round(l2_ms, 2),
                    "L3": round(l3_ms, 2),
                },
                "calibrated": False,
            },
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            reflex_emotion=self._banks["audio_scene"][2].get(scene_top, "neutral"),
            description=(
                f"Сцена L1: {scene_top} (cosine={scene_score:.2f}); "
                f"L2 обработал {len(window_features)} окон и {len(specialist_candidates)} отдельных групп признаков; "
                f"переходов между соседними окнами: "
                f"{sum(1 for item in window_changes if item['scene_candidate_changed'])}. "
                "Сходства — непроверенные кандидаты, не вероятности."
            ),
        )
        return obs

    def describe_audio_pcm16(
        self,
        pcm16: bytes,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        temporal_detail: bool = False,
    ) -> DetailedObservation:
        """Describe raw PCM16 with the low-cost live path by default."""
        np = self.np
        raw = np.frombuffer(pcm16, dtype=np.int16)
        if channels > 1:
            raw = raw.reshape(-1, channels).mean(axis=1).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(sample_rate))
            w.writeframes(raw.tobytes())
        return self.describe_audio_detailed(
            buf.getvalue(), temporal_detail=bool(temporal_detail)
        )

    # -------------------------------------------------------------------
    # 3-ring self-awareness perception snapshot
    # -------------------------------------------------------------------

    def perception_snapshot(
        self,
        *,
        user_activity: dict[str, Any] | None = None,
        system_state: dict[str, Any] | None = None,
        avatar_state: dict[str, Any] | None = None,
        recent_observations: list[dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Build 3-ring self-awareness snapshot for JAWL brain context.

        Ring 1: User (voice, activity, attention, mood)
        Ring 2: External world (screen, audio, music, environment)
        Ring 3: Self (avatar pose, emotion, active goal, latency, resources)
        """
        moment = time.time() if now is None else float(now)
        user = user_activity or {}
        system = system_state or {}
        avatar = avatar_state or {}

        # Ring 1: User
        ring_user = {
            "idle_seconds": user.get("idle_seconds"),
            "typing_intensity": user.get("typing_intensity", 0.0),
            "window_switches": user.get("window_switches", 0),
            "focus_stability": user.get("focus_stability", "unknown"),
            "last_speech_modulation": user.get("speech_modulation"),
            "voice_active": user.get("voice_active", False),
        }

        # Ring 2: External world (from recent observations)
        ring_world = {
            "screen_scene": None,
            "screen_style": None,
            "audio_type": None,
            "music_genre": None,
            "music_genre_candidate": None,
            "music_bpm": None,
            "music_key": None,
            "ocr_text": None,
            "scene_changed": False,
            "vibe_score": None,
        }
        for obs in (recent_observations or []):
            if not isinstance(obs, dict):
                continue
            modality = obs.get("modality", "")
            if modality == "vision":
                ring_world["screen_scene"] = obs.get("level0")
                ring_world["screen_style"] = obs.get("level1", {}).get("style")
                ring_world["ocr_text"] = obs.get("level2", {}).get("ocr_text", "")[:200]
                ring_world["scene_changed"] = obs.get("scene_changed", False)
            elif modality == "audio":
                ring_world["audio_type"] = obs.get("level0")
                genre_candidates = (
                    obs.get("level2", {}).get("specialist_candidates", {}).get("music_genre", [])
                )
                ring_world["music_genre"] = genre_candidates[0]["label"] if genre_candidates else None
                ring_world["music_genre_candidate"] = (
                    {**genre_candidates[0], "source": "unverified_candidate"}
                    if genre_candidates else None
                )
                ring_world["music_bpm"] = obs.get("level2", {}).get("dsp", {}).get("bpm")
                ring_world["music_key"] = obs.get("level2", {}).get("dsp", {}).get("key")
                ring_world["vibe_score"] = obs.get("vibe_score")

        # Ring 3: Self
        ring_self = {
            "avatar_emotion": avatar.get("emotion", "neutral"),
            "avatar_intensity": avatar.get("intensity", 0.0),
            "avatar_pose": avatar.get("pose", "idle"),
            "active_goal": avatar.get("active_goal"),
            "is_speaking": avatar.get("is_speaking", False),
            "perception_latency_ms": avatar.get("perception_latency_ms"),
            "resource_mode": system.get("resource_mode", "standard"),
            "cpu_load": system.get("cpu_load"),
            "ram_load": system.get("ram_load"),
            "gaming_mode": system.get("gaming_mode", False),
        }

        return {
            "timestamp": moment,
            "ring_user": ring_user,
            "ring_world": ring_world,
            "ring_self": ring_self,
            "raw_media_persisted": False,
        }

    # -------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------

    def close(self) -> None:
        """Terminate OCR pipe and release resources."""
        with self._ocr_lock:
            if self._ocr_proc is not None:
                try:
                    self._ocr_proc.stdin.write("QUIT\n")
                    self._ocr_proc.stdin.flush()
                except Exception:
                    pass
                try:
                    self._ocr_proc.terminate()
                except Exception:
                    pass
                self._ocr_proc = None
                self._ocr_ready = False

    def __del__(self) -> None:
        self.close()


class Eg2VisionDescriber:
    """Drop-in replacement for OpenAICompatibleVisionClient backed by EG2 + WinOCR + UIA."""

    def __init__(self, describer: DetailedSensoryDescriber) -> None:
        self.describer = describer

    def describe(self, prompt: str, observation: dict[str, Any]) -> str:
        image = observation.get("image") if isinstance(observation, dict) else None
        if not isinstance(image, dict):
            raise RuntimeError("screen observation has no image")
        encoded = image.get("data_base64")
        if not isinstance(encoded, str) or not encoded:
            raise RuntimeError("screen observation image is invalid")
        import base64

        image_bytes = base64.b64decode(encoded)
        obs = self.describer.describe_screen_detailed(image_bytes, prompt=prompt)
        parts = [obs.description]
        uia = observation.get("uia")
        if isinstance(uia, dict) and isinstance(uia.get("elements"), list):
            names = [
                str(el.get("name") or "").strip()
                for el in uia["elements"][:12]
                if isinstance(el, dict) and str(el.get("name") or "").strip()
            ]
            if names:
                parts.append("UIA-элементы: " + ", ".join(names[:8]))
        return "; ".join(parts)[:4000]


_MUSIC_MOOD_RU = {
    "melancholic": "меланхоличное",
    "energetic": "энергичное",
    "tense": "напряжённое",
    "calm": "спокойное",
    "triumphant": "торжествующее",
}


class Eg2AudioDescriptionProvider:
    """AudioDescriptionProvider backed by EG2 + NumPy DSP (no external model)."""

    name = "eg2-audio"

    def __init__(self, describer: DetailedSensoryDescriber) -> None:
        self.describer = describer

    def describe(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        channels: int,
        clip_id: str,
    ) -> dict[str, Any]:
        obs = self.describer.describe_audio_pcm16(
            pcm16, sample_rate=sample_rate, channels=channels,
            temporal_detail=False,
        )
        result = safe_detailed_audio_claim(obs)
        hypotheses = self._candidate_hypotheses(obs)
        if hypotheses:
            result["candidate_hypotheses"] = hypotheses
        return result

    @staticmethod
    def _candidate_hypotheses(observation: DetailedObservation) -> list[dict[str, Any]]:
        """Preserve bounded EG2 rankings without presenting them as findings.

        Similarities are encoder rankings, not calibrated probabilities. The
        ambient fusion layer requires overlapping positive YAMNet evidence
        before showing these music-specialist candidates to the brain.
        """
        level1 = getattr(observation, "level1", {})
        level2 = getattr(observation, "level2", {})
        specialist = level2.get("specialist_candidates", {}) if isinstance(level2, dict) else {}
        if not isinstance(specialist, dict):
            specialist = {}
        banks: list[tuple[str, str]] = [
            ("audio_scene", "audio_scene"),
            ("music_genre", "music_genre"),
            ("music_mood", "music_mood"),
            ("music_vocals", "music_vocals"),
            ("music_drums", "music_drums"),
            ("music_bass", "music_bass"),
            ("music_electronic", "music_electronic"),
        ]
        result: list[dict[str, Any]] = []
        for category, key in banks:
            values = (
                level1.get("scene_candidates", [])
                if key == "audio_scene" and isinstance(level1, dict)
                else specialist.get(key, [])
            )
            if not isinstance(values, list):
                continue
            candidates = []
            for item in values[:2]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                similarity = item.get("similarity")
                if (
                    not label or isinstance(similarity, bool)
                    or not isinstance(similarity, (int, float))
                    or not 0 <= float(similarity) <= 1
                ):
                    continue
                candidates.append({"label": label[:80], "similarity": round(float(similarity), 4)})
            if candidates:
                result.append({"category": category, "candidates": candidates})
        return result


__all__ = [
    "DetailedObservation",
    "DetailedSensoryDescriber",
    "Eg2AudioDescriptionProvider",
    "Eg2VisionDescriber",
    "AUDIO_SCENE_BANK",
    "VISUAL_STYLE_BANK",
    "VISUAL_ELEMENT_BANK",
    "MUSIC_GENRE_BANK",
    "MUSIC_MOOD_BANK",
    "SPEECH_STYLE_BANK",
    "MUSIC_VOCAL_BANK",
    "MUSIC_DRUMS_BANK",
    "MUSIC_BASS_BANK",
    "MUSIC_ELECTRONIC_BANK",
]
