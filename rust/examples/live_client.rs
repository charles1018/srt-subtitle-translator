//! 實機對照工具：以 Rust client 翻譯一個 SRT，輸出 JSON 供與 Python 版比對。
//!
//! 上下文固定為「前一句、本句、後一句」，與 `rust/tools/live_client.py` 相同。
//!
//! ```bash
//! cargo run --release --example live_client -- <config_dir> <srt> <content_type> <language_pair> <model> <out.json> [concurrency] [netflix]
//! ```

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use serde_json::json;
use srt_translator::client::{ClientOptions, LlmType, NetflixStyleConfig, RetryPolicy, TranslationClient};
use srt_translator::prompt::PromptManager;
use srt_translator::subtitle::SubRipFile;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [config_dir, srt, content_type, language_pair, model, out, rest @ ..] = args.as_slice() else {
        anyhow::bail!("用法: live_client <config_dir> <srt> <content_type> <language_pair> <model> <out.json> [concurrency] [netflix]");
    };
    let concurrency: usize = rest.first().map_or(Ok(1), |s| s.parse())?;
    let netflix = rest.get(1).is_some_and(|s| s == "netflix");

    let mut pm = PromptManager::open(&PathBuf::from(config_dir))?;
    pm.set_content_type(content_type)?;
    pm.set_language_pair(language_pair)?;
    let mut options = ClientOptions::new(LlmType::Llamacpp);
    options.base_url = Some("http://127.0.0.1:8080".into());
    options.netflix_style = NetflixStyleConfig { enabled: netflix, ..Default::default() };
    let client = TranslationClient::new(options, Arc::new(pm), None);

    let subs = SubRipFile::open(&PathBuf::from(srt))?;
    let texts: Vec<String> = subs.items.iter().map(|s| s.text.clone()).collect();
    let items: Vec<(String, Vec<String>, usize)> = (0..texts.len())
        .map(|i| {
            let start = i.saturating_sub(1);
            let end = (i + 2).min(texts.len());
            (texts[i].clone(), texts[start..end].to_vec(), i - start)
        })
        .collect();

    let started = Instant::now();
    let translations: Vec<String> = if concurrency <= 1 {
        let mut out = Vec::new();
        for (text, context, idx) in &items {
            out.push(
                client.translate_with_retry(text, context, model, Some(*idx), false, RetryPolicy::default()).await,
            );
        }
        out
    } else {
        let batch: Vec<(String, Vec<String>)> = items.iter().map(|(t, c, _)| (t.clone(), c.clone())).collect();
        let indices: Vec<Option<usize>> = items.iter().map(|(_, _, i)| Some(*i)).collect();
        client.translate_batch(&batch, model, concurrency, Some(&indices), false).await
    };
    let elapsed = started.elapsed().as_secs_f64();
    let metrics = client.metrics();
    std::fs::write(
        out,
        serde_json::to_string_pretty(&json!({
            "elapsed": elapsed,
            "translations": translations,
            "total_tokens": metrics.total_tokens,
            "failed": metrics.failed_requests,
        }))?,
    )?;
    println!("Rust: {} 條，{elapsed:.1} 秒，失敗 {}", translations.len(), metrics.failed_requests);
    Ok(())
}
