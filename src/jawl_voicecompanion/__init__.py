"""Safe Phase 1 core for JAWL VoiceCompanion."""

from .gateway import TextGateway, validate_response_envelope
from .jawl_gateway_contract import JawlGatewayEvent
from .hostos_policy import HostOSPolicy
from .hostos_tools import HostOSExecutor, ToolSpec
from .browser_adapter import BrowserAdapter
from .approvals import ApprovalStore
from .models import AccessLevel, RiskClass, ToolRequest
from .arbiter import TurnArbiter, TurnPriority
from .screen_adapter import ScreenCaptureAdapter
from .vision import (
    JawlNativeVisionExecutor,
    OpenAICompatibleVisionClient,
    VisionActionPlan,
    VisionLookService,
    VisionPlanError,
    VisionPlanExecutor,
)
from .presence import ScreenDeltaWatcher
from .attention import AttentionPresence
from .jawl_events import JawlEventFileSink
from .tts import CozyVoiceHttpClient, Qwen3TTSHttpClient, TeraTTSHttpClient, TTSService, TTSUnavailable, TTSCancelled, VoxCPMHttpClient
from .voicemem_client import VoiceMemAsyncIngest, VoiceMemProcessClient, VoiceMemUnavailable
from .jawl_web import JawlWebAdapter, JawlWebChatAdapter, JawlWebUnavailable
from .ambient_memory import AmbientMemoryBuffer, AmbientTriageScheduler
from .ambient_triage import (
    AmbientTriageProvider,
    AmbientTriageUnavailable,
    OllamaTriageProvider,
    OpenAICompatibleTriageProvider,
)
from .ambient_audio import AmbientAudioASRBridge, AmbientAudioDisabled, AmbientAudioService, PlaybackSuppression
from .resources import ResourceGovernor
from .asr import UtteranceBuffer
from .supervisor import RuntimeSupervisor, WorkerSpec
from .audio_understanding import (
    AUDIO_DESCRIPTION_SCHEMA,
    AUDIO_KINDS,
    AudioDescription,
    AudioDescriptionService,
    AudioDescriptionUnavailable,
    validate_audio_description,
)
from .windows_pointer import WindowsPointerAdapter
from .windows_keyboard import WindowsKeyboardAdapter
from .llm import LLMUnavailable, OpenAICompatibleChatClient
from .system_audio import SystemAudioLoopback, SystemAudioUnavailable
from .process_loopback import ProcessLoopbackBridge, ProcessLoopbackError
try:
    from .visual_stream import DXGIScreenCapture, SceneDeltaDetector, VisualStreamWorker
except ImportError:
    DXGIScreenCapture = None  # type: ignore
    SceneDeltaDetector = None  # type: ignore
    VisualStreamWorker = None  # type: ignore

try:
    from .episodic_visual_memory import EpisodicVisualMemory
except ImportError:
    EpisodicVisualMemory = None  # type: ignore

try:
    from .affective_engine import AffectiveEngine
except ImportError:
    AffectiveEngine = None  # type: ignore

try:
    from .windows_smtc import WindowsSMTCAdapter
except ImportError:
    WindowsSMTCAdapter = None  # type: ignore

try:
    from .narrative_consolidator import NarrativeConsolidator
except ImportError:
    NarrativeConsolidator = None  # type: ignore

try:
    from .event_policy import EventPolicy, PolicyDecision
except ImportError:
    EventPolicy = None  # type: ignore
    PolicyDecision = None  # type: ignore

try:
    from .scene_state import EpistemicObservationState, SceneState
except ImportError:
    EpistemicObservationState = None  # type: ignore
    SceneState = None  # type: ignore

try:
    from .perception_fusion import CognitiveTurnDecision, PerceptionFusion, SenseNovaPerceptionBridge
except ImportError:
    CognitiveTurnDecision = None  # type: ignore
    PerceptionFusion = None  # type: ignore
    SenseNovaPerceptionBridge = None  # type: ignore
from .audit import AuditLog
from .stream_chat import StreamChatIngestor, StreamChatLimits
from .runtime_profile import RuntimeProfile
from .companion_runtime import CompanionRuntime

__all__ = [
    "AccessLevel",
    "HostOSPolicy",
    "HostOSExecutor",
    "BrowserAdapter",
    "ApprovalStore",
    "ApprovalStore",
    "RiskClass",
    "TextGateway",
    "validate_response_envelope",
    "JawlGatewayEvent",
    "ToolRequest",
    "ToolSpec",
    "TurnArbiter",
    "TurnPriority",
    "ScreenCaptureAdapter",
    "OpenAICompatibleVisionClient",
    "JawlNativeVisionExecutor",
    "VisionLookService",
    "VisionActionPlan",
    "VisionPlanError",
    "VisionPlanExecutor",
    "ScreenDeltaWatcher",
    "AttentionPresence",
    "JawlEventFileSink",
    "CozyVoiceHttpClient",
    "TeraTTSHttpClient",
    "Qwen3TTSHttpClient",
    "VoxCPMHttpClient",
    "TTSService",
    "TTSUnavailable",
    "TTSCancelled",
    "VoiceMemProcessClient",
    "VoiceMemAsyncIngest",
    "VoiceMemUnavailable",
    "JawlWebAdapter",
    "JawlWebChatAdapter",
    "JawlWebUnavailable",
    "AmbientMemoryBuffer",
    "AmbientTriageScheduler",
    "AmbientTriageProvider",
    "AmbientTriageUnavailable",
    "OllamaTriageProvider",
    "OpenAICompatibleTriageProvider",
    "AmbientAudioASRBridge",
    "AmbientAudioDisabled",
    "AmbientAudioService",
    "PlaybackSuppression",
    "ResourceGovernor",
    "UtteranceBuffer",
    "RuntimeSupervisor",
    "WorkerSpec",
    "AUDIO_DESCRIPTION_SCHEMA",
    "AUDIO_KINDS",
    "AudioDescription",
    "AudioDescriptionService",
    "AudioDescriptionUnavailable",
    "validate_audio_description",
    "WindowsPointerAdapter",
    "WindowsKeyboardAdapter",
    "LLMUnavailable",
    "OpenAICompatibleChatClient",
    "SystemAudioLoopback",
    "SystemAudioUnavailable",
    "ProcessLoopbackBridge",
    "ProcessLoopbackError",
    "DXGIScreenCapture",
    "SceneDeltaDetector",
    "VisualStreamWorker",
    "EpisodicVisualMemory",
    "AffectiveEngine",
    "WindowsSMTCAdapter",
    "NarrativeConsolidator",
    "EventPolicy",
    "PolicyDecision",
    "SceneState",
    "EpistemicObservationState",
    "CognitiveTurnDecision",
    "PerceptionFusion",
    "SenseNovaPerceptionBridge",
    "AuditLog",
    "StreamChatIngestor",
    "StreamChatLimits",
    "RuntimeProfile",
    "CompanionRuntime",
]
