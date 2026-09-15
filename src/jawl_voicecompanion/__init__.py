"""Safe Phase 1 core for JAWL VoiceCompanion."""

from .gateway import TextGateway, validate_response_envelope
from .jawl_gateway_contract import JawlGatewayEvent
from .hostos_policy import HostOSPolicy
from .hostos_tools import HostOSExecutor, ToolSpec
from .browser_adapter import BrowserAdapter
from .approvals import ApprovalStore
from .avatar import AvatarAssetStore
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
from .asr import ASRNoSpeech, ASRUnavailable, ExternalASRService, OpenAICompatibleASRClient
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
    "AvatarAssetStore",
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
    "ASRNoSpeech",
    "ASRUnavailable",
    "ExternalASRService",
    "OpenAICompatibleASRClient",
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
    "AuditLog",
    "StreamChatIngestor",
    "StreamChatLimits",
    "RuntimeProfile",
    "CompanionRuntime",
]
