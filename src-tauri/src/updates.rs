use base64::{engine::general_purpose::STANDARD, Engine as _};
use ed25519_dalek::{Signature, VerifyingKey};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    fs,
    io::{Cursor, Read},
    path::{Path, PathBuf},
};
use tauri::{AppHandle, Manager};
use tempfile::Builder;
use zip::ZipArchive;

#[derive(Clone, Debug, Deserialize)]
struct UpdateConfig {
    tools: ToolUpdateConfig,
}

#[derive(Clone, Debug, Deserialize)]
struct ToolUpdateConfig {
    enabled: bool,
    catalog_url: String,
    require_signature: bool,
    public_key: String,
}

#[derive(Clone, Debug, Deserialize)]
struct SignedEnvelope {
    payload: String,
    signature: String,
}

#[derive(Clone, Debug, Deserialize)]
struct ToolCatalog {
    schema_version: u32,
    tools: Vec<CatalogTool>,
}

#[derive(Clone, Debug, Deserialize)]
struct CatalogTool {
    id: String,
    name: String,
    version: String,
    url: String,
    sha256: String,
    #[serde(default)]
    size: u64,
}

#[derive(Clone, Debug, Deserialize)]
struct PackageManifest {
    id: String,
    version: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ToolUpdateInfo {
    id: String,
    name: String,
    current_version: Option<String>,
    version: String,
    size: u64,
    is_new: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct ToolUpdateCheck {
    configured: bool,
    updates: Vec<ToolUpdateInfo>,
    message: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ToolUpdateInstallResult {
    installed: Vec<String>,
    message: String,
}

fn version(value: &str) -> Version {
    Version::parse(value.trim_start_matches('v')).unwrap_or_else(|_| Version::new(0, 0, 0))
}

pub(crate) fn config_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("update-config.json");
    if dev_path.is_file() {
        return Ok(dev_path);
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("리소스 폴더를 찾지 못했습니다: {error}"))?;
    for candidate in [
        resource_dir.join("update-config.json"),
        resource_dir.join("_up_").join("update-config.json"),
    ] {
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err("업데이트 설정 파일을 찾지 못했습니다.".to_string())
}

fn read_config(app: &AppHandle) -> Result<UpdateConfig, String> {
    let raw = fs::read_to_string(config_path(app)?)
        .map_err(|error| format!("업데이트 설정을 읽지 못했습니다: {error}"))?;
    serde_json::from_str(&raw).map_err(|error| format!("업데이트 설정 형식 오류: {error}"))
}

fn verify_catalog(config: &ToolUpdateConfig, bytes: &[u8]) -> Result<ToolCatalog, String> {
    if !config.require_signature {
        let catalog: ToolCatalog = serde_json::from_slice(bytes)
            .map_err(|error| format!("도구 카탈로그 형식 오류: {error}"))?;
        if catalog.schema_version != 1 {
            return Err("지원하지 않는 도구 카탈로그 버전입니다.".to_string());
        }
        return Ok(catalog);
    }

    let envelope: SignedEnvelope = serde_json::from_slice(bytes)
        .map_err(|error| format!("서명된 카탈로그 형식 오류: {error}"))?;
    let public_key = STANDARD
        .decode(config.public_key.trim())
        .map_err(|_| "도구 업데이트 공개키가 올바르지 않습니다.".to_string())?;
    let public_key: [u8; 32] = public_key
        .try_into()
        .map_err(|_| "도구 업데이트 공개키 길이가 올바르지 않습니다.".to_string())?;
    let verifying_key = VerifyingKey::from_bytes(&public_key)
        .map_err(|_| "도구 업데이트 공개키를 읽지 못했습니다.".to_string())?;
    let signature_bytes = STANDARD
        .decode(envelope.signature.trim())
        .map_err(|_| "도구 카탈로그 서명이 올바르지 않습니다.".to_string())?;
    let signature = Signature::from_slice(&signature_bytes)
        .map_err(|_| "도구 카탈로그 서명 길이가 올바르지 않습니다.".to_string())?;
    let payload = STANDARD
        .decode(envelope.payload.trim())
        .map_err(|_| "도구 카탈로그 본문이 올바르지 않습니다.".to_string())?;

    verifying_key
        .verify_strict(&payload, &signature)
        .map_err(|_| "도구 카탈로그 서명 검증에 실패했습니다.".to_string())?;

    let catalog: ToolCatalog = serde_json::from_slice(&payload)
        .map_err(|error| format!("도구 카탈로그 형식 오류: {error}"))?;
    if catalog.schema_version != 1 {
        return Err("지원하지 않는 도구 카탈로그 버전입니다.".to_string());
    }
    Ok(catalog)
}

fn download_catalog(config: &ToolUpdateConfig) -> Result<ToolCatalog, String> {
    let response = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|error| error.to_string())?
        .get(&config.catalog_url)
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("도구 카탈로그를 내려받지 못했습니다: {error}"))?;
    let bytes = response
        .bytes()
        .map_err(|error| format!("도구 카탈로그를 읽지 못했습니다: {error}"))?;
    verify_catalog(config, &bytes)
}

fn scan_versions(root: &Path, versions: &mut HashMap<String, String>) {
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let manifest_path = entry.path().join("manifest.json");
        let Ok(raw) = fs::read_to_string(manifest_path) else {
            continue;
        };
        let Ok(manifest) = serde_json::from_str::<PackageManifest>(&raw) else {
            continue;
        };
        let replace = versions
            .get(&manifest.id)
            .map(|current| version(&manifest.version) > version(current))
            .unwrap_or(true);
        if replace {
            versions.insert(manifest.id, manifest.version);
        }
    }
}

fn installed_versions(app: &AppHandle) -> HashMap<String, String> {
    let mut versions = HashMap::new();
    let dev_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("tools");
    scan_versions(&dev_root, &mut versions);

    if let Ok(resource_dir) = app.path().resource_dir() {
        scan_versions(&resource_dir.join("tools"), &mut versions);
        scan_versions(&resource_dir.join("_up_").join("tools"), &mut versions);
    }
    if let Ok(data_dir) = app.path().app_data_dir() {
        scan_versions(&data_dir.join("tools"), &mut versions);
    }
    versions
}

fn available_updates(app: &AppHandle, catalog: &ToolCatalog) -> Vec<ToolUpdateInfo> {
    let installed = installed_versions(app);
    catalog
        .tools
        .iter()
        .filter_map(|tool| {
            let current = installed.get(&tool.id);
            if current
                .map(|value| version(&tool.version) <= version(value))
                .unwrap_or(false)
            {
                return None;
            }
            Some(ToolUpdateInfo {
                id: tool.id.clone(),
                name: tool.name.clone(),
                current_version: current.cloned(),
                version: tool.version.clone(),
                size: tool.size,
                is_new: current.is_none(),
            })
        })
        .collect()
}

#[tauri::command]
pub fn check_tool_updates(app: AppHandle) -> Result<ToolUpdateCheck, String> {
    let config = read_config(&app)?;
    if !config.tools.enabled || config.tools.catalog_url.trim().is_empty() {
        return Ok(ToolUpdateCheck {
            configured: false,
            updates: Vec::new(),
            message: "도구 업데이트 주소가 아직 설정되지 않았습니다.".to_string(),
        });
    }
    if config.tools.require_signature && config.tools.public_key.trim().is_empty() {
        return Err("도구 업데이트 공개키가 설정되지 않았습니다.".to_string());
    }

    let catalog = download_catalog(&config.tools)?;
    let updates = available_updates(&app, &catalog);
    let message = if updates.is_empty() {
        "모든 도구가 최신 상태입니다.".to_string()
    } else {
        format!("설치할 도구 업데이트가 {}개 있습니다.", updates.len())
    };
    Ok(ToolUpdateCheck {
        configured: true,
        updates,
        message,
    })
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn unpack_zip(bytes: &[u8], target: &Path) -> Result<(), String> {
    let mut archive =
        ZipArchive::new(Cursor::new(bytes)).map_err(|error| format!("ZIP 열기 실패: {error}"))?;
    for index in 0..archive.len() {
        let mut file = archive
            .by_index(index)
            .map_err(|error| format!("ZIP 항목 읽기 실패: {error}"))?;
        let Some(relative) = file.enclosed_name() else {
            return Err("안전하지 않은 ZIP 경로가 포함되어 있습니다.".to_string());
        };
        let output = target.join(relative);
        if file.is_dir() {
            fs::create_dir_all(&output).map_err(|error| error.to_string())?;
            continue;
        }
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let mut output_file = fs::File::create(&output).map_err(|error| error.to_string())?;
        std::io::copy(&mut file, &mut output_file).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn find_package_root(root: &Path, expected_id: &str, expected_version: &str) -> Result<PathBuf, String> {
    let direct = root.join("manifest.json");
    let mut candidates = vec![direct];
    if let Ok(entries) = fs::read_dir(root) {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                candidates.push(entry.path().join("manifest.json"));
            }
        }
    }
    for manifest_path in candidates {
        let Ok(raw) = fs::read_to_string(&manifest_path) else {
            continue;
        };
        let Ok(manifest) = serde_json::from_str::<PackageManifest>(&raw) else {
            continue;
        };
        if manifest.id == expected_id && manifest.version == expected_version {
            return manifest_path
                .parent()
                .map(Path::to_path_buf)
                .ok_or_else(|| "도구 패키지 폴더가 올바르지 않습니다.".to_string());
        }
    }
    Err("도구 패키지의 ID 또는 버전이 카탈로그와 일치하지 않습니다.".to_string())
}

fn install_one(app: &AppHandle, tool: &CatalogTool, tools_dir: &Path) -> Result<(), String> {
    let mut response = reqwest::blocking::get(&tool.url)
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("{} 다운로드 실패: {error}", tool.name))?;
    let mut bytes = Vec::new();
    response
        .read_to_end(&mut bytes)
        .map_err(|error| format!("{} 다운로드 읽기 실패: {error}", tool.name))?;
    if sha256_hex(&bytes).to_lowercase() != tool.sha256.trim().to_lowercase() {
        return Err(format!("{} 파일 해시가 일치하지 않습니다.", tool.name));
    }

    fs::create_dir_all(tools_dir).map_err(|error| error.to_string())?;
    let staging = Builder::new()
        .prefix(".tool-update-")
        .tempdir_in(tools_dir)
        .map_err(|error| format!("임시 폴더 생성 실패: {error}"))?;
    unpack_zip(&bytes, staging.path())?;
    let package_root = find_package_root(staging.path(), &tool.id, &tool.version)?;

    let destination = tools_dir.join(&tool.id);
    let backup = tools_dir.join(format!(".{}.backup", tool.id));
    if backup.exists() {
        fs::remove_dir_all(&backup).map_err(|error| error.to_string())?;
    }
    if destination.exists() {
        fs::rename(&destination, &backup)
            .map_err(|error| format!("기존 도구 백업 실패: {error}"))?;
    }

    if let Err(error) = fs::rename(&package_root, &destination) {
        if backup.exists() && !destination.exists() {
            let _ = fs::rename(&backup, &destination);
        }
        return Err(format!("새 도구 설치 실패: {error}"));
    }
    if backup.exists() {
        fs::remove_dir_all(&backup).map_err(|error| error.to_string())?;
    }
    drop(staging);
    let _ = app;
    Ok(())
}

#[tauri::command]
pub fn install_tool_updates(app: AppHandle) -> Result<ToolUpdateInstallResult, String> {
    let config = read_config(&app)?;
    if !config.tools.enabled || config.tools.catalog_url.trim().is_empty() {
        return Err("도구 업데이트 주소가 설정되지 않았습니다.".to_string());
    }
    let catalog = download_catalog(&config.tools)?;
    let updates = available_updates(&app, &catalog);
    if updates.is_empty() {
        return Ok(ToolUpdateInstallResult {
            installed: Vec::new(),
            message: "모든 도구가 최신 상태입니다.".to_string(),
        });
    }

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("사용자 데이터 폴더를 찾지 못했습니다: {error}"))?;
    let tools_dir = data_dir.join("tools");
    let update_ids: Vec<_> = updates.iter().map(|update| update.id.as_str()).collect();
    let mut installed = Vec::new();
    for tool in catalog
        .tools
        .iter()
        .filter(|tool| update_ids.contains(&tool.id.as_str()))
    {
        install_one(&app, tool, &tools_dir)?;
        installed.push(tool.id.clone());
    }

    Ok(ToolUpdateInstallResult {
        message: format!("도구 {}개를 설치했습니다.", installed.len()),
        installed,
    })
}
