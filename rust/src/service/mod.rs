//! 字幕檔翻譯服務（對等 Python `services/factory.py` 的 `TranslationService`）。
//!
//! 流程：載入字幕 → 依啟發式決定每句的上下文視窗 → 分段送翻（一般/智慧批次/structure-text 批次）
//! → 服務層後處理（OpenCC s2twp、原文感知片語、台灣詞彙、術語表、標點）→ 套用顯示模式 → 輸出。
//!
//! 已知限制（與 Python 相同）：所有格式都以 SRT 解析器讀取，.vtt/.ass 只有符合 SRT 區塊結構的部分會被翻譯。

mod control;
pub mod heuristics;

pub use control::TaskControl;

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use log::{info, warn};

use crate::cache::{CacheKey, CacheManager};
use crate::client::TranslationClient;
use crate::config::ConfigFile;
use crate::error::{Error, Result};
use crate::glossary::GlossaryManager;
use crate::output::{resolve_output_path, ConflictChoice, OutputSettings};
use crate::prompt::PromptManager;
use crate::py;
use crate::subtitle::SubRipFile;
use crate::text::japanese;
use crate::text::normalize;
use crate::text::opencc;
use crate::tools::srt_tools::{batch_string_to_texts, texts_to_batch_string};
use heuristics::RuntimeSettings;

/// 字幕顯示模式。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DisplayMode {
    TranslationOnly,
    TranslationAbove,
    OriginalAbove,
    Bilingual,
}

impl DisplayMode {
    /// 支援 CLI 別名「僅譯文」；未知值與 Python 相同視為雙語對照。
    pub fn parse(s: &str) -> Self {
        match s {
            "僅顯示翻譯" | "僅譯文" => Self::TranslationOnly,
            "翻譯在上" => Self::TranslationAbove,
            "原文在上" => Self::OriginalAbove,
            _ => Self::Bilingual,
        }
    }

    fn apply(self, original: &str, translation: &str) -> String {
        match self {
            Self::TranslationOnly => translation.to_string(),
            Self::TranslationAbove => format!("{translation}\n{original}"),
            Self::OriginalAbove | Self::Bilingual => format!("{original}\n{translation}"),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct TranslationStats {
    pub total_translations: u64,
    pub cached_translations: u64,
    pub failed_translations: u64,
    pub processing_time: f64,
}

/// 服務層設定（來源：`user_settings.json`）。
#[derive(Debug, Clone)]
pub struct ServiceSettings {
    pub runtime: RuntimeSettings,
    pub preserve_punctuation: bool,
}

impl ServiceSettings {
    pub fn from_user_config(user: &ConfigFile) -> Self {
        let int = |key: &str, default: i64, min: i64, max: i64| {
            user.get(key)
                .and_then(|v| v.as_i64().filter(|_| v.is_i64() || v.is_u64()))
                .map_or(default, |v| v.clamp(min, max))
        };
        Self {
            runtime: RuntimeSettings {
                batch_size: int("translation.batch_size", 10, 1, heuristics::MAX_STRUCTURED_BATCH_SIZE),
                max_context_items: int("translation.max_context_items", heuristics::DEFAULT_MAX_CONTEXT_ITEMS, 0, 7),
                smart_context_enabled: user.get_bool("translation.smart_context_enabled", true),
                compact_prompt_enabled: user.get_bool("translation.compact_prompt_enabled", true),
                terminology_enabled: user.get_bool("translation.terminology_enabled", true),
            },
            preserve_punctuation: user.get("preserve_punctuation").is_none_or(|v| {
                // Python 以真值判斷：非布林值依 JSON 真值規則
                match v {
                    serde_json::Value::Bool(b) => *b,
                    serde_json::Value::Null => false,
                    serde_json::Value::Number(n) => n.as_f64() != Some(0.0),
                    serde_json::Value::String(s) => !s.is_empty(),
                    serde_json::Value::Array(a) => !a.is_empty(),
                    serde_json::Value::Object(o) => !o.is_empty(),
                }
            }),
        }
    }
}

/// 單一檔案翻譯參數。
#[derive(Debug, Clone)]
pub struct FileJob {
    pub source_lang: String,
    pub target_lang: String,
    pub model_name: String,
    pub parallel_requests: usize,
    pub display_mode: DisplayMode,
    pub use_structure_text: bool,
    pub use_cache: bool,
}

/// 單一檔案的翻譯結果。
#[derive(Debug, Clone)]
pub struct FileOutcome {
    pub output_path: PathBuf,
    pub total: usize,
    pub successful: usize,
    pub failed: usize,
    pub elapsed: String,
}

fn is_failed(translation: &str) -> bool {
    translation.is_empty() || translation.starts_with("[翻譯錯誤")
}

/// 與 Python `get_elapsed_time_str` 相同的耗時格式。
pub fn format_elapsed(seconds: f64) -> String {
    if seconds < 60.0 {
        return format!("{} 秒", seconds as u64);
    }
    let total = seconds as u64;
    let (minutes, secs) = (total / 60, total % 60);
    if minutes < 60 {
        return format!("{minutes} 分 {secs} 秒");
    }
    format!("{} 小時 {} 分 {secs} 秒", minutes / 60, minutes % 60)
}

pub struct TranslationService {
    client: TranslationClient,
    prompt: Arc<PromptManager>,
    cache: Option<Arc<CacheManager>>,
    glossary: Option<GlossaryManager>,
    settings: ServiceSettings,
    stats: Mutex<TranslationStats>,
}

impl TranslationService {
    pub fn new(
        client: TranslationClient,
        prompt: Arc<PromptManager>,
        cache: Option<Arc<CacheManager>>,
        glossary: Option<GlossaryManager>,
        settings: ServiceSettings,
    ) -> Self {
        Self { client, prompt, cache, glossary, settings, stats: Mutex::new(TranslationStats::default()) }
    }

    pub fn client(&self) -> &TranslationClient {
        &self.client
    }

    pub fn stats(&self) -> TranslationStats {
        self.stats.lock().unwrap().clone()
    }

    fn llm(&self) -> &'static str {
        self.client.llm_type.as_str()
    }

    /// 服務層後處理：OpenCC s2twp → 原文感知片語 → 台灣詞彙 → 術語表 → 標點。
    pub fn post_process_translation(&self, original: &str, translated: &str) -> String {
        if translated.is_empty() {
            return String::new();
        }
        let mut text = opencc::s2twp(translated);
        text = normalize::normalize_source_aware_subtitle_phrases(original, &text);
        text = normalize::normalize_taiwan_subtitle_terminology(&text);
        if self.settings.runtime.terminology_enabled {
            if let Some(g) = &self.glossary {
                if g.active().next().is_some() {
                    text = g.apply(&text, "", "");
                }
            }
        }
        if self.settings.preserve_punctuation {
            return py::strip(&text).to_string();
        }
        const CN_PUNCTUATION: &str = "，。！？；：\"\"（）【】《》〈〉、…—～·「」『』〔〕";
        const EN_PUNCTUATION: &str = ",.!?;:\\\"'()[]<>-_";
        let replaced: String = text
            .chars()
            .map(|c| if CN_PUNCTUATION.contains(c) || EN_PUNCTUATION.contains(c) { ' ' } else { c })
            .collect();
        py::strip(&normalize::collapse_whitespace(&replaced, " ")).to_string()
    }

    fn incr(&self, f: impl FnOnce(&mut TranslationStats)) {
        f(&mut self.stats.lock().unwrap());
    }

    /// 服務層單句翻譯（先查快取，經 client 重試翻譯後再做服務層後處理並寫快取）。
    pub async fn translate_text(
        &self,
        text: &str,
        context: &[String],
        model_name: &str,
        current_index: Option<usize>,
        use_cache: bool,
    ) -> String {
        if py::strip(text).is_empty() {
            return String::new();
        }
        self.incr(|s| s.total_translations += 1);
        let llm = self.llm();
        let style = self.prompt.current_style.as_str();
        let prompt_version = self.prompt.get_prompt_version(llm, None, None, Some(model_name), false);
        let effective = self.prompt.get_effective_cache_context_texts(text, context, llm, model_name, current_index);
        let key = CacheKey::new(text, model_name, style, &prompt_version);
        if use_cache {
            if let Some(cached) = self.cache.as_ref().and_then(|c| c.get(key, &effective)).filter(|c| !c.is_empty()) {
                if japanese::cache_rejection_reason(text, &cached).is_none() {
                    self.incr(|s| s.cached_translations += 1);
                    return cached;
                }
            }
        }
        let started = Instant::now();
        let translation = self
            .client
            .translate_with_retry(text, context, model_name, current_index, use_cache, Default::default())
            .await;
        if translation.starts_with("[翻譯錯誤") {
            return translation;
        }
        let translation = self.post_process_translation(text, &translation);
        if use_cache && japanese::cache_rejection_reason(text, &translation).is_none() {
            if let Some(cache) = &self.cache {
                cache.store(key, &translation, &effective);
            }
        }
        let elapsed = started.elapsed().as_secs_f64();
        self.incr(|s| s.processing_time += elapsed);
        translation
    }

    /// 服務層批量翻譯：client 批量翻譯後逐句做服務層後處理（此路徑不另寫快取，與 Python 相同）。
    pub async fn translate_batch(
        &self,
        items: &[(String, Vec<String>)],
        model_name: &str,
        concurrent_limit: usize,
        current_indices: &[Option<usize>],
        use_cache: bool,
    ) -> Vec<String> {
        let raw =
            self.client.translate_batch(items, model_name, concurrent_limit, Some(current_indices), use_cache).await;
        items
            .iter()
            .zip(raw)
            .map(|((text, _), t)| {
                if t.is_empty() || t.starts_with("[翻譯錯誤") {
                    t
                } else {
                    self.post_process_translation(text, &t)
                }
            })
            .collect()
    }

    fn context_for(snapshot: &[String], index: usize, window: usize) -> (Vec<String>, usize) {
        let start = index.saturating_sub(window);
        let end = (index + window + 1).min(snapshot.len());
        (snapshot[start..end].to_vec(), index - start)
    }

    /// 以單一請求翻譯多句（structure-text）；行數或句型檢查失敗時重試一次，仍失敗則退回逐句翻譯。
    async fn translate_batch_structure_text(
        &self,
        snapshot: &[String],
        batch_indices: &[usize],
        job: &FileJob,
    ) -> Vec<String> {
        let model = job.model_name.as_str();
        let llm = self.llm();
        let source_texts: Vec<String> = batch_indices.iter().map(|&i| snapshot[i].clone()).collect();
        let style = self.prompt.current_style.clone();
        let batch_version = self.prompt.get_prompt_version(llm, None, None, Some(model), true);
        let mut results: Vec<Option<String>> = vec![None; source_texts.len()];
        let mut pending: Vec<usize> = (0..source_texts.len()).collect();

        if job.use_cache {
            if let Some(cache) = &self.cache {
                pending.clear();
                for (pos, source) in source_texts.iter().enumerate() {
                    let cached =
                        cache.get(CacheKey::new(source, model, &style, &batch_version), &[]).filter(|c| !c.is_empty());
                    match cached {
                        Some(c) if japanese::cache_rejection_reason(source, &c).is_none() => {
                            results[pos] = Some(c);
                            self.incr(|s| s.cached_translations += 1);
                        }
                        _ => pending.push(pos),
                    }
                }
                if pending.is_empty() {
                    return results.into_iter().map(Option::unwrap_or_default).collect();
                }
            }
        }

        let pending_texts: Vec<String> = pending.iter().map(|&p| source_texts[p].clone()).collect();
        let n = pending_texts.len();
        let prefixed = format!(
            "[BATCH: {n} lines — translate each line, output exactly {n} lines]\n{}",
            texts_to_batch_string(&pending_texts)
        );
        const MAX_ATTEMPTS: usize = 2;
        for attempt in 0..MAX_ATTEMPTS {
            if n != source_texts.len() {
                info!("智慧批次翻譯 {n} 個字幕（快取命中 {}）", source_texts.len() - n);
            } else {
                info!("智慧批次翻譯 {n} 個字幕");
            }
            let translation = self.translate_text(&prefixed, &[], model, None, false).await;
            if translation.is_empty() || translation.contains("[翻譯錯誤") {
                warn!("結構-文本分離: 批次翻譯回傳錯誤 (attempt {}/{MAX_ATTEMPTS})", attempt + 1);
                continue;
            }
            let translated = match batch_string_to_texts(&translation, n) {
                Ok(t) => t,
                Err(e) => {
                    warn!("結構-文本分離: attempt {}/{MAX_ATTEMPTS} 失敗: {e}", attempt + 1);
                    continue;
                }
            };
            if !heuristics::batch_translation_preserves_sentence_mood(&pending_texts, &translated) {
                warn!("結構-文本分離: 批次翻譯句型檢查失敗 (attempt {}/{MAX_ATTEMPTS})", attempt + 1);
                if attempt + 1 < MAX_ATTEMPTS {
                    continue;
                }
                break;
            }
            for (&pos, t) in pending.iter().zip(&translated) {
                let processed = self.post_process_translation(&source_texts[pos], t);
                if job.use_cache {
                    if let Some(cache) = &self.cache {
                        cache.store(CacheKey::new(&source_texts[pos], model, &style, &batch_version), &processed, &[]);
                    }
                }
                results[pos] = Some(processed);
            }
            return results.into_iter().map(Option::unwrap_or_default).collect();
        }

        warn!("結構-文本分離: 退回到標準逐條翻譯模式");
        let mut items = Vec::new();
        let mut indices = Vec::new();
        for &pos in &pending {
            let idx = batch_indices[pos];
            let window =
                heuristics::context_window_for_text(&snapshot[idx], &self.settings.runtime, Some(&job.source_lang));
            let (context, current) = Self::context_for(snapshot, idx, window);
            items.push((snapshot[idx].clone(), context));
            indices.push(Some(current));
        }
        let fallback = self.translate_batch(&items, model, job.parallel_requests, &indices, job.use_cache).await;
        for (&pos, t) in pending.iter().zip(fallback) {
            results[pos] = Some(t);
        }
        results.into_iter().map(Option::unwrap_or_default).collect()
    }

    /// 翻譯整份字幕檔並寫出；全部失敗時不輸出檔案並回傳錯誤。
    ///
    /// `progress(current, total)` 每處理一句呼叫一次；`ask` 用於輸出檔名衝突（ask 模式）。
    pub async fn translate_subtitle_file(
        &self,
        path: &Path,
        job: &FileJob,
        output: &OutputSettings,
        progress: &(dyn Fn(usize, usize) + Sync),
        ask: Option<&dyn Fn(&Path) -> ConflictChoice>,
    ) -> Result<FileOutcome> {
        self.translate_subtitle_file_with_control(path, job, output, progress, ask, None).await
    }

    /// 同 [`Self::translate_subtitle_file`]，可由 `control` 暫停/停止。
    ///
    /// 每個批次送出前檢查暫停（進行中的批次會完成）；停止時中止進行中的請求、
    /// 不寫出輸出檔並回傳 [`Error::Cancelled`]。
    pub async fn translate_subtitle_file_with_control(
        &self,
        path: &Path,
        job: &FileJob,
        output: &OutputSettings,
        progress: &(dyn Fn(usize, usize) + Sync),
        ask: Option<&dyn Fn(&Path) -> ConflictChoice>,
        control: Option<&TaskControl>,
    ) -> Result<FileOutcome> {
        let control = control.cloned().unwrap_or_default();
        let started = Instant::now();
        *self.stats.lock().unwrap() = TranslationStats::default();
        let mut subs = SubRipFile::open(path)?;
        let snapshot: Vec<String> = subs.items.iter().map(|s| s.text.clone()).collect();
        let total = snapshot.len();
        let runtime = self.settings.runtime;
        let batch_size = runtime.batch_size as usize;
        let is_openai = self.llm() == "openai";
        let standard_chunk =
            if is_openai { job.parallel_requests.clamp(1, 5) } else { (job.parallel_requests.max(1) * 2).min(20) };
        let source_lang = Some(job.source_lang.as_str());

        let windows: Vec<usize> =
            snapshot.iter().map(|t| heuristics::context_window_for_text(t, &runtime, source_lang)).collect();
        let batchable: Vec<bool> = (0..total)
            .map(|i| {
                !py::strip(&snapshot[i]).is_empty()
                    && is_openai
                    && batch_size > 1
                    && windows[i] == 0
                    && heuristics::is_batch_safe_short_text(&snapshot[i], source_lang)
            })
            .collect();

        let (mut successful, mut failed, mut done) = (0usize, 0usize, 0usize);
        let mut last_error = String::new();
        let mut cursor = 0;
        progress(0, total);
        while cursor < total {
            control.checkpoint().await?;
            let (batch_indices, translations): (Vec<usize>, Vec<String>) = if job.use_structure_text {
                let indices: Vec<usize> = (cursor..(cursor + batch_size).min(total)).collect();
                cursor += indices.len();
                let t = control.run(self.translate_batch_structure_text(&snapshot, &indices, job)).await?;
                (indices, t)
            } else {
                let run = heuristics::count_consecutive_batchable(cursor, &batchable, batch_size);
                if run >= 2 {
                    let indices: Vec<usize> = (cursor..cursor + run).collect();
                    cursor += run;
                    let t = control.run(self.translate_batch_structure_text(&snapshot, &indices, job)).await?;
                    (indices, t)
                } else {
                    let mut indices = Vec::new();
                    while cursor < total && indices.len() < standard_chunk {
                        let upcoming = heuristics::count_consecutive_batchable(cursor, &batchable, batch_size);
                        if !indices.is_empty() && upcoming >= 2 {
                            break;
                        }
                        indices.push(cursor);
                        cursor += 1;
                    }
                    let mut items = Vec::new();
                    let mut current = Vec::new();
                    for &idx in &indices {
                        let (context, ci) = Self::context_for(&snapshot, idx, windows[idx]);
                        items.push((snapshot[idx].clone(), context));
                        current.push(Some(ci));
                    }
                    let t = control
                        .run(self.translate_batch(
                            &items,
                            &job.model_name,
                            job.parallel_requests,
                            &current,
                            job.use_cache,
                        ))
                        .await?;
                    (indices, t)
                }
            };

            for (pos, &idx) in batch_indices.iter().enumerate() {
                done += 1;
                match translations.get(pos) {
                    None => {
                        failed += 1;
                        last_error = "[翻譯錯誤: 批量翻譯結果數量不足]".into();
                    }
                    Some(t) if is_failed(t) => {
                        failed += 1;
                        last_error = if t.is_empty() { "[翻譯錯誤: 空白翻譯結果]".into() } else { t.clone() };
                        warn!("字幕翻譯失敗: 檔案={}, 字幕索引={}, 錯誤={last_error}", path.display(), idx + 1);
                    }
                    Some(t) => {
                        let item = &mut subs.items[idx];
                        item.text = job.display_mode.apply(&item.text, t);
                        successful += 1;
                    }
                }
                progress(done, total);
            }
            if failed > 0 {
                self.incr(|s| s.failed_translations = failed as u64);
            }
        }

        control.checkpoint().await?;
        let elapsed = format_elapsed(started.elapsed().as_secs_f64());
        if successful == 0 && failed > 0 {
            return Err(Error::Translation {
                message: if last_error.is_empty() { "所有字幕翻譯失敗".into() } else { last_error },
                details: Default::default(),
            });
        }
        let output_path = resolve_output_path(path, &job.target_lang, output, ask)?
            .ok_or_else(|| Error::file("無法建立輸出路徑（已略過）"))?;
        subs.save(&output_path)?;
        Ok(FileOutcome { output_path, total, successful, failed, elapsed })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn elapsed_format() {
        assert_eq!(format_elapsed(5.9), "5 秒");
        assert_eq!(format_elapsed(125.0), "2 分 5 秒");
        assert_eq!(format_elapsed(3725.0), "1 小時 2 分 5 秒");
    }

    #[test]
    fn display_modes() {
        assert_eq!(DisplayMode::parse("僅譯文").apply("a", "甲"), "甲");
        assert_eq!(DisplayMode::parse("翻譯在上").apply("a", "甲"), "甲\na");
        assert_eq!(DisplayMode::parse("雙語對照").apply("a", "甲"), "a\n甲");
    }
}
