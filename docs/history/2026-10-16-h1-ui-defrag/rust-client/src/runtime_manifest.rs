//! Bounded, fail-closed loader for the shared runtime manifest contract.
//!
//! The Python loader is canonical. This module implements the Rust client's
//! manifest subset plus validation of the complete shared schema.

use serde::de::{MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

const MANIFEST_REL: &str = "config/runtime.manifest.json";
const LOCAL_NAME: &str = "runtime.manifest.local.json";
const MAX_JSON_BYTES: u64 = 128 * 1024;

const TOP: &[&str] = &[
    "schema_version",
    "created",
    "purpose",
    "repo_root",
    "profile",
    "ports",
    "models",
    "mic",
    "brain",
    "profile_script",
    "launch",
    "vision",
];
const PORTS: &[&str] = &[
    "control",
    "presentation",
    "jawl_console",
    "opencode_relay",
    "qwen3_vl",
    "bonsai_coding",
    "tera_tts",
    "brain_port",
    "reserved",
];
const MODELS: &[&str] = &[
    "llama_server_exe",
    "brain_server_exe",
    "qwen3_vl_model",
    "qwen3_vl_mmproj",
    "bonsai_model",
    "bonsai_mmproj",
    "tera_python",
    "tera_release",
];
const BRAIN: &[&str] = &[
    "provider",
    "model",
    "llm_url",
    "use_relay",
    "raised_by",
    "relay_override",
    "context_size",
    "max_output_tokens",
    "device",
    "threads",
    "gpu_layers",
];

struct UniqueJson(Value);
impl<'de> Deserialize<'de> for UniqueJson {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct UniqueVisitor;
        impl<'de> Visitor<'de> for UniqueVisitor {
            type Value = UniqueJson;
            fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
                formatter.write_str("JSON value without duplicate object fields")
            }
            fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Bool(value)))
            }
            fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Number(value.into())))
            }
            fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Number(value.into())))
            }
            fn visit_f64<E: serde::de::Error>(self, value: f64) -> Result<Self::Value, E> {
                serde_json::Number::from_f64(value)
                    .map(|n| UniqueJson(Value::Number(n)))
                    .ok_or_else(|| E::custom("invalid number"))
            }
            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::String(value.into())))
            }
            fn visit_string<E: serde::de::Error>(self, value: String) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::String(value)))
            }
            fn visit_none<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Null))
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = seq.next_element::<UniqueJson>()? {
                    values.push(value.0);
                }
                Ok(UniqueJson(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut values = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(serde::de::Error::custom("duplicate field"));
                    }
                    let value = map.next_value::<UniqueJson>()?;
                    values.insert(key, value.0);
                }
                Ok(UniqueJson(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(UniqueVisitor)
    }
}

#[derive(Debug, Default)]
pub struct ManifestConfig {
    pub discovered_root: PathBuf,
    pub repo_root: Option<PathBuf>,
    pub profile: Option<String>,
    pub control_port: Option<u16>,
    pub presentation_port: Option<u16>,
    pub jawl_console_port: Option<u16>,
    pub relay_port: Option<u16>,
    pub qwen3_vl_port: Option<u16>,
    pub bonsai_port: Option<u16>,
    pub llama_server_exe: Option<PathBuf>,
    pub qwen3_vl_model: Option<PathBuf>,
    pub qwen3_vl_mmproj: Option<PathBuf>,
    pub bonsai_model: Option<PathBuf>,
    pub bonsai_mmproj: Option<PathBuf>,
    pub mic_prefer: Option<String>,
    pub brain_model: Option<String>,
    pub brain_use_relay: Option<bool>,
    pub profile_script: Option<PathBuf>,
}

/// Resolve by explicit root first, then cwd/executable ancestors. A missing
/// manifest returns `None`; the caller may then use its documented dev defaults.
pub fn load(
    explicit_root: Option<&Path>,
    cwd: &Path,
    executable: Option<&Path>,
) -> Result<Option<ManifestConfig>, String> {
    let root = find_root(explicit_root, cwd, executable)?;
    let Some(root) = root else { return Ok(None) };
    let canonical = root.join(MANIFEST_REL);
    let local = canonical.with_file_name(LOCAL_NAME);
    let canonical_exists = canonical
        .try_exists()
        .map_err(|_| "runtime manifest is not readable JSON")?;
    let local_exists = local
        .try_exists()
        .map_err(|_| "runtime manifest is not readable JSON")?;
    if local_exists && !canonical_exists {
        return Err("runtime manifest is not readable JSON".into());
    }

    let mut merged = if canonical_exists {
        read_object(&canonical)?
    } else {
        Map::new()
    };
    if local_exists {
        let overlay = read_object(&local)?;
        deep_merge(&mut merged, overlay);
    }
    // The Python contract requires the canonical file whenever an override is
    // present; Rust defaults apply only when neither file exists.
    if canonical_exists {
        apply_legacy_defaults(&mut merged)?;
        validate(&merged)?;
    }
    let mut config = to_config(&merged);
    config.discovered_root = root;
    Ok(Some(config))
}

fn find_root(
    explicit: Option<&Path>,
    cwd: &Path,
    executable: Option<&Path>,
) -> Result<Option<PathBuf>, String> {
    if let Some(root) = explicit {
        let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
        if !manifest_candidates_exist(&root)? {
            return Err("explicit repository root has no runtime manifest".into());
        }
        return Ok(Some(root));
    }
    let mut candidates = Vec::new();
    for start in [Some(cwd), executable.and_then(Path::parent)]
        .into_iter()
        .flatten()
    {
        for parent in start.ancestors() {
            if !candidates.iter().any(|p: &PathBuf| p == parent) {
                candidates.push(parent.to_path_buf());
            }
        }
    }
    for root in candidates {
        if manifest_candidates_exist(&root)? {
            return Ok(Some(root));
        }
    }
    Ok(None)
}

fn manifest_candidates_exist(root: &Path) -> Result<bool, String> {
    let canonical = root
        .join(MANIFEST_REL)
        .try_exists()
        .map_err(|_| "runtime manifest is not readable JSON")?;
    let local = root
        .join("config")
        .join(LOCAL_NAME)
        .try_exists()
        .map_err(|_| "runtime manifest is not readable JSON")?;
    Ok(canonical || local)
}

fn read_object(path: &Path) -> Result<Map<String, Value>, String> {
    let file = File::open(path).map_err(|_| "runtime manifest is not readable JSON")?;
    let mut bytes = Vec::new();
    file.take(MAX_JSON_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "runtime manifest is not readable JSON")?;
    if bytes.len() as u64 > MAX_JSON_BYTES {
        return Err("runtime manifest exceeds the size limit".into());
    }
    let value: UniqueJson =
        serde_json::from_slice(&bytes).map_err(|_| "runtime manifest is not readable JSON")?;
    let value = value.0;
    let object = value
        .as_object()
        .ok_or("runtime manifest must be a JSON object")?;
    reject_secret_keys(&value, 0)?;
    Ok(object.clone())
}

fn reject_secret_keys(value: &Value, depth: usize) -> Result<(), String> {
    if depth > 64 {
        return Err("runtime manifest nesting exceeds the limit".into());
    }
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                let lower = key.to_ascii_lowercase();
                if lower != "max_output_tokens"
                    && [
                        "token",
                        "secret",
                        "password",
                        "api_key",
                        "private_key",
                        "access_key",
                        "credential",
                        "authorization",
                    ]
                    .iter()
                    .any(|word| lower.contains(word))
                {
                    return Err("runtime manifest contains a secret-bearing field".into());
                }
                reject_secret_keys(child, depth + 1)?;
            }
        }
        Value::Array(items) => {
            for child in items {
                reject_secret_keys(child, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn deep_merge(base: &mut Map<String, Value>, overlay: Map<String, Value>) {
    for (key, value) in overlay {
        match (base.get_mut(&key), value) {
            (Some(Value::Object(target)), Value::Object(source)) => deep_merge(target, source),
            (_, value) => {
                base.insert(key, value);
            }
        }
    }
}

fn apply_legacy_defaults(root: &mut Map<String, Value>) -> Result<(), String> {
    for key in ["ports", "models", "mic", "brain", "launch", "vision"] {
        root.entry(key).or_insert_with(|| Value::Object(Map::new()));
        if !root[key].is_object() {
            return Err("runtime manifest contains an invalid section".into());
        }
    }
    let inferred = root
        .get("brain")
        .and_then(|b| b.get("llm_url"))
        .and_then(Value::as_str)
        .and_then(|url| url.split("://").nth(1))
        .and_then(|authority| authority.split('/').next())
        .and_then(|authority| authority.rsplit(':').next())
        .and_then(|port| port.parse::<u64>().ok());
    let ports = root
        .get_mut("ports")
        .and_then(Value::as_object_mut)
        .unwrap();
    ports
        .entry("brain_port")
        .or_insert_with(|| json_num(inferred.unwrap_or(8990)));
    let brain_port = ports
        .get("brain_port")
        .and_then(Value::as_u64)
        .unwrap_or(8990);
    let models = root
        .get_mut("models")
        .and_then(Value::as_object_mut)
        .unwrap();
    let legacy_exe = models
        .get("llama_server_exe")
        .cloned()
        .unwrap_or_else(|| Value::String("llama-server.exe".into()));
    models.entry("brain_server_exe").or_insert(legacy_exe);
    let brain = root
        .get_mut("brain")
        .and_then(Value::as_object_mut)
        .unwrap();
    brain
        .entry("llm_url")
        .or_insert_with(|| Value::String(format!("http://127.0.0.1:{brain_port}/v1")));
    for (key, value) in [
        ("context_size", 65536),
        ("max_output_tokens", 2048),
        ("threads", 12),
        ("gpu_layers", 99),
    ] {
        brain.entry(key).or_insert_with(|| json_num(value));
    }
    brain
        .entry("device")
        .or_insert_with(|| Value::String("CUDA1".into()));
    let launch = root
        .get_mut("launch")
        .and_then(Value::as_object_mut)
        .unwrap();
    launch.entry("run_seconds").or_insert_with(|| json_num(0));
    launch
        .entry("tts_provider")
        .or_insert_with(|| Value::String("tera".into()));
    let vision = root
        .get_mut("vision")
        .and_then(Value::as_object_mut)
        .unwrap();
    vision
        .entry("url")
        .or_insert_with(|| Value::String("http://127.0.0.1:8986/v1".into()));
    vision
        .entry("model")
        .or_insert_with(|| Value::String("bonsai".into()));
    vision.entry("auto_start").or_insert(Value::Bool(false));
    Ok(())
}

fn json_num(number: u64) -> Value {
    Value::Number(number.into())
}

fn validate(root: &Map<String, Value>) -> Result<(), String> {
    keys(root, TOP, "root")?;
    if root.get("schema_version").and_then(Value::as_u64) != Some(1) {
        return Err("runtime manifest schema version is unsupported".into());
    }
    for key in [
        "created",
        "purpose",
        "repo_root",
        "profile",
        "profile_script",
    ] {
        if let Some(value) = root.get(key) {
            text(value, key, 4096)?;
        }
    }
    let profile = root
        .get("profile")
        .and_then(Value::as_str)
        .unwrap_or("daily");
    if profile.is_empty()
        || profile.len() > 48
        || !profile.as_bytes()[0].is_ascii_alphanumeric()
        || !profile
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
    {
        return Err("runtime manifest profile must be one safe directory name".into());
    }
    let upper = profile.to_ascii_uppercase();
    if ["CON", "PRN", "AUX", "NUL"].contains(&upper.as_str())
        || (1..=9).any(|n| upper == format!("COM{n}") || upper == format!("LPT{n}"))
    {
        return Err("runtime manifest profile uses a reserved directory name".into());
    }
    let ports = object(root, "ports")?;
    keys(ports, PORTS, "ports")?;
    let mut service_ports = Vec::new();
    for (key, value) in ports {
        if key == "reserved" {
            continue;
        }
        service_ports.push((key.as_str(), port(value, &format!("ports.{key}"))?));
    }
    let reserved = ports
        .get("reserved")
        .map(|v| {
            v.as_array()
                .ok_or("runtime manifest has invalid reserved ports")
        })
        .transpose()?
        .cloned()
        .unwrap_or_default();
    if reserved.len() > 64 {
        return Err("runtime manifest has invalid reserved ports".into());
    }
    let mut reserved_ports = HashSet::from([8765u16]);
    for value in &reserved {
        reserved_ports.insert(port(value, "ports.reserved")?);
    }
    let mut seen = HashSet::new();
    for (_, value) in &service_ports {
        if *value == 8765 {
            return Err("runtime manifest uses a reserved port".into());
        }
        if !seen.insert(*value) {
            return Err("runtime manifest ports collide".into());
        }
        if reserved_ports.contains(value) {
            return Err("runtime manifest ports collide with a reserved port".into());
        }
    }
    let models = object(root, "models")?;
    keys(models, MODELS, "models")?;
    for (key, value) in models {
        text(value, &format!("models.{key}"), 4096)?;
    }
    let mic = root
        .get("mic")
        .and_then(Value::as_object)
        .ok_or("runtime manifest contains an invalid section")?;
    keys(mic, &["prefer"], "mic")?;
    if let Some(value) = mic.get("prefer") {
        label(value, "mic.prefer")?;
    }
    let brain = object(root, "brain")?;
    keys(brain, BRAIN, "brain")?;
    label(
        brain
            .get("model")
            .ok_or("runtime manifest has an invalid brain.model")?,
        "brain.model",
    )?;
    for key in ["provider", "device"] {
        if let Some(value) = brain.get(key) {
            label(value, &format!("brain.{key}"))?;
        }
    }
    if let Some(value) = brain.get("raised_by") {
        text(value, "brain.raised_by", 4096)?;
    }
    for (key, min, max) in [
        ("context_size", 512, 1048576),
        ("max_output_tokens", 1, 65536),
        ("threads", 1, 128),
        ("gpu_layers", 0, 256),
    ] {
        if let Some(value) = brain.get(key) {
            integer_range(value, min, max, &format!("brain.{key}"))?;
        }
    }
    let context = brain
        .get("context_size")
        .and_then(Value::as_u64)
        .ok_or("runtime manifest has an invalid brain.context_size")?;
    let output = brain
        .get("max_output_tokens")
        .and_then(Value::as_u64)
        .ok_or("runtime manifest has an invalid brain.max_output_tokens")?;
    if output >= context {
        return Err("runtime manifest output budget must be smaller than its context".into());
    }
    if brain.get("use_relay").is_some_and(|v| !v.is_boolean()) {
        return Err("runtime manifest has an invalid brain.use_relay".into());
    }
    if let Some(relay) = brain.get("relay_override") {
        let relay = relay
            .as_object()
            .ok_or("runtime manifest has an invalid relay override")?;
        keys(
            relay,
            &["note", "model", "relay_port"],
            "brain.relay_override",
        )?;
        if let Some(value) = relay.get("model") {
            label(value, "brain.relay_override.model")?;
        }
        if let Some(value) = relay.get("relay_port") {
            port(value, "brain.relay_override.relay_port")?;
        }
        if let Some(value) = relay.get("note") {
            text(value, "brain.relay_override.note", 4096)?;
        }
    }
    let (_, brain_url_port) = loopback_url(
        brain
            .get("llm_url")
            .ok_or("runtime manifest has an invalid brain.llm_url")?,
        "brain.llm_url",
    )?;
    let configured_brain_port = ports
        .get("brain_port")
        .map(|v| port(v, "ports.brain_port"))
        .transpose()?
        .ok_or("runtime manifest has an invalid ports.brain_port")?;
    if brain_url_port != configured_brain_port {
        return Err("runtime manifest brain URL does not match its port".into());
    }
    let launch = object(root, "launch")?;
    keys(launch, &["run_seconds", "tts_provider"], "launch")?;
    if let Some(value) = launch.get("run_seconds") {
        integer_range(value, 0, u64::MAX, "launch.run_seconds")?;
    }
    if let Some(value) = launch.get("tts_provider") {
        let provider = label(value, "launch.tts_provider")?;
        if !["tera", "omnivoice", "voxcpm"].contains(&provider) {
            return Err("runtime manifest has an unsupported launch.tts_provider".into());
        }
    }
    let vision = object(root, "vision")?;
    keys(vision, &["url", "model", "alias", "auto_start"], "vision")?;
    if let Some(value) = vision.get("url") {
        loopback_url(value, "vision.url")?;
    }
    for key in ["model", "alias"] {
        if let Some(value) = vision.get(key) {
            label(value, &format!("vision.{key}"))?;
        }
    }
    if vision.get("auto_start").is_some_and(|v| !v.is_boolean()) {
        return Err("runtime manifest has an invalid vision.auto_start".into());
    }
    Ok(())
}

fn object<'a>(root: &'a Map<String, Value>, key: &str) -> Result<&'a Map<String, Value>, String> {
    root.get(key)
        .and_then(Value::as_object)
        .ok_or_else(|| format!("runtime manifest {key} must be an object"))
}
fn keys(value: &Map<String, Value>, allowed: &[&str], where_: &str) -> Result<(), String> {
    if value.keys().any(|key| !allowed.contains(&key.as_str())) {
        return Err(format!(
            "runtime manifest has unsupported fields in {where_}"
        ));
    }
    Ok(())
}
fn text<'a>(value: &'a Value, where_: &str, max: usize) -> Result<&'a str, String> {
    let value = value
        .as_str()
        .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
    if value.trim().is_empty() || value.len() > max || value.contains('\0') {
        return Err(format!("runtime manifest has an invalid {where_}"));
    }
    Ok(value)
}
fn label<'a>(value: &'a Value, where_: &str) -> Result<&'a str, String> {
    let value = text(value, where_, 128)?;
    if !value.as_bytes()[0].is_ascii_alphanumeric()
        || !value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_.+-".contains(&c))
    {
        return Err(format!("runtime manifest has an invalid {where_}"));
    }
    Ok(value)
}
fn port(value: &Value, where_: &str) -> Result<u16, String> {
    let value = value
        .as_u64()
        .filter(|n| (1..=65535).contains(n))
        .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
    Ok(value as u16)
}
fn integer_range(value: &Value, min: u64, max: u64, where_: &str) -> Result<u64, String> {
    value
        .as_u64()
        .filter(|n| *n >= min && *n <= max)
        .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))
}
fn loopback_url(value: &Value, where_: &str) -> Result<(String, u16), String> {
    let url = text(value, where_, 2048)?;
    let (scheme, rest) = url
        .split_once("://")
        .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
    if !scheme.eq_ignore_ascii_case("http") {
        return Err(format!("runtime manifest has an invalid {where_}"));
    }
    let (authority, path) = rest
        .split_once('/')
        .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
    let path = format!("/{path}");
    if authority.contains('@')
        || authority.contains(['?', '#'])
        || !["/v1", "/v1/"].contains(&path.as_str())
    {
        return Err(format!("runtime manifest has an invalid {where_}"));
    }
    let (host, port) = if authority.starts_with('[') {
        let close = authority
            .find(']')
            .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
        let host = &authority[1..close];
        let port = authority
            .get(close + 1..)
            .and_then(|tail| tail.strip_prefix(':'))
            .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
        (host, port)
    } else {
        let pair = authority
            .rsplit_once(':')
            .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
        if pair.0.contains(':') {
            return Err(format!("runtime manifest has an invalid {where_}"));
        }
        pair
    };
    if !(host == "localhost"
        || host
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback()))
    {
        return Err(format!("runtime manifest has an invalid {where_}"));
    }
    let port: u16 = port
        .parse()
        .ok()
        .filter(|p| *p > 0)
        .ok_or_else(|| format!("runtime manifest has an invalid {where_}"))?;
    Ok((url.to_owned(), port))
}

fn to_config(root: &Map<String, Value>) -> ManifestConfig {
    let get_port = |key: &str| root.get("ports")?.get(key)?.as_u64().map(|n| n as u16);
    let get_model = |key: &str| root.get("models")?.get(key)?.as_str().map(PathBuf::from);
    let brain = &root["brain"];
    ManifestConfig {
        discovered_root: PathBuf::new(),
        repo_root: root
            .get("repo_root")
            .and_then(Value::as_str)
            .map(PathBuf::from),
        profile: root
            .get("profile")
            .and_then(Value::as_str)
            .map(str::to_owned),
        control_port: get_port("control"),
        presentation_port: get_port("presentation"),
        jawl_console_port: get_port("jawl_console"),
        relay_port: get_port("opencode_relay"),
        qwen3_vl_port: get_port("qwen3_vl"),
        bonsai_port: get_port("bonsai_coding"),
        llama_server_exe: get_model("llama_server_exe"),
        qwen3_vl_model: get_model("qwen3_vl_model"),
        qwen3_vl_mmproj: get_model("qwen3_vl_mmproj"),
        bonsai_model: get_model("bonsai_model"),
        bonsai_mmproj: get_model("bonsai_mmproj"),
        mic_prefer: root
            .get("mic")
            .and_then(|v| v.get("prefer"))
            .and_then(Value::as_str)
            .map(str::to_owned),
        brain_model: brain
            .get("model")
            .and_then(Value::as_str)
            .map(str::to_owned),
        brain_use_relay: brain.get("use_relay").and_then(Value::as_bool),
        profile_script: root
            .get("profile_script")
            .and_then(Value::as_str)
            .map(PathBuf::from),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TempRoot(PathBuf);
    impl TempRoot {
        fn new() -> Self {
            let id = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let path = std::env::temp_dir()
                .join(format!("jawl-manifest-test-{}-{id}", std::process::id()));
            std::fs::create_dir_all(path.join("config")).unwrap();
            Self(path)
        }
        fn write(&self, name: &str, value: &str) {
            std::fs::write(self.0.join("config").join(name), value).unwrap();
        }
    }
    impl Drop for TempRoot {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    const BASE: &str = r#"{"schema_version":1,"ports":{"control":2367,"presentation":8766,"jawl_console":8770,"opencode_relay":8891,"qwen3_vl":8983,"bonsai_coding":8986,"tera_tts":9889,"brain_port":8990},"models":{},"brain":{"model":"local-bonsai2","llm_url":"http://127.0.0.1:8990/v1"}}"#;

    #[test]
    fn local_manifest_recursively_overlays_and_maps_effective_values() {
        let root = TempRoot::new();
        root.write("runtime.manifest.json", BASE);
        root.write(
            "runtime.manifest.local.json",
            r#"{"ports":{"control":3367},"brain":{"use_relay":true}}"#,
        );
        let loaded = load(Some(&root.0), &root.0, None).unwrap().unwrap();
        assert_eq!(loaded.control_port, Some(3367));
        assert_eq!(loaded.presentation_port, Some(8766));
        assert_eq!(loaded.brain_use_relay, Some(true));
        assert_eq!(loaded.brain_model.as_deref(), Some("local-bonsai2"));
    }

    #[test]
    fn malformed_or_oversized_manifest_fails_without_defaults() {
        let root = TempRoot::new();
        root.write("runtime.manifest.json", "{");
        assert!(load(Some(&root.0), &root.0, None)
            .unwrap_err()
            .contains("readable JSON"));
        root.write(
            "runtime.manifest.json",
            r#"{"schema_version":1,"schema_version":1}"#,
        );
        assert!(load(Some(&root.0), &root.0, None)
            .unwrap_err()
            .contains("readable JSON"));
        root.write("runtime.manifest.json", BASE);
        root.write("runtime.manifest.local.json", "not-json");
        assert!(load(Some(&root.0), &root.0, None)
            .unwrap_err()
            .contains("readable JSON"));
        root.write(
            "runtime.manifest.local.json",
            &" ".repeat(MAX_JSON_BYTES as usize + 1),
        );
        assert!(load(Some(&root.0), &root.0, None)
            .unwrap_err()
            .contains("size limit"));
        let local_only = TempRoot::new();
        local_only.write("runtime.manifest.local.json", r#"{"profile":"daily"}"#);
        assert!(load(Some(&local_only.0), &local_only.0, None)
            .unwrap_err()
            .contains("readable JSON"));
        root.write("runtime.manifest.local.json", "{}");
        root.write(
            "runtime.manifest.json",
            &" ".repeat(MAX_JSON_BYTES as usize + 1),
        );
        assert!(load(Some(&root.0), &root.0, None)
            .unwrap_err()
            .contains("size limit"));
    }

    #[test]
    fn profile_names_follow_python_safe_and_windows_reserved_name_rules() {
        for (profile, expected) in [
            ("team_alpha-2".to_owned(), true),
            ("CON".to_owned(), false),
            ("com1".to_owned(), false),
            ("bad/name".to_owned(), false),
            ("a".repeat(49), false),
        ] {
            let root = TempRoot::new();
            let json = format!(
                r#"{{"schema_version":1,"profile":"{profile}","ports":{{"control":2367,"presentation":8766,"jawl_console":8770,"opencode_relay":8891,"qwen3_vl":8983,"bonsai_coding":8986,"tera_tts":9889,"brain_port":8990}},"models":{{}},"brain":{{"model":"local-bonsai2","llm_url":"http://127.0.0.1:8990/v1"}}}}"#
            );
            root.write("runtime.manifest.json", &json);
            assert_eq!(
                load(Some(&root.0), &root.0, None).is_ok(),
                expected,
                "{profile}"
            );
        }
    }

    #[test]
    fn reserved_and_brain_tts_or_service_port_collisions_fail_closed() {
        for (local, expected) in [
            (r#"{"ports":{"control":8765}}"#, "reserved"),
            (r#"{"ports":{"brain_port":9889}}"#, "collide"),
            (r#"{"ports":{"qwen3_vl":2367}}"#, "collide"),
        ] {
            let root = TempRoot::new();
            root.write("runtime.manifest.json", BASE);
            root.write("runtime.manifest.local.json", local);
            assert!(
                load(Some(&root.0), &root.0, None)
                    .unwrap_err()
                    .contains(expected),
                "{local}"
            );
        }
    }

    #[test]
    fn discovery_walks_cwd_and_executable_parents_and_explicit_root_wins() {
        let root = TempRoot::new();
        root.write("runtime.manifest.json", BASE);
        let child = root.0.join("rust-client").join("target").join("debug");
        std::fs::create_dir_all(&child).unwrap();
        assert!(load(None, &child, None).unwrap().is_some());
        let unrelated_cwd = TempRoot::new();
        assert!(load(None, &unrelated_cwd.0, Some(&child.join("jawl.exe")))
            .unwrap()
            .is_some());
        let other = TempRoot::new();
        other.write("runtime.manifest.json", BASE);
        assert!(load(Some(&other.0), &child, None).unwrap().is_some());
    }
}
