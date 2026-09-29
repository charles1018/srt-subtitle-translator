//! 終端機日誌：格式與 Python CLI 的 `logging.basicConfig` 相同（`時間 - 等級 - 訊息`，輸出到 stderr）。

use log::{Level, LevelFilter, Log, Metadata, Record};

struct StderrLogger;

impl Log for StderrLogger {
    fn enabled(&self, metadata: &Metadata<'_>) -> bool {
        metadata.level() <= log::max_level() && metadata.target().starts_with("srt_translator")
    }

    fn log(&self, record: &Record<'_>) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let level = match record.level() {
            Level::Error => "ERROR",
            Level::Warn => "WARNING",
            Level::Info => "INFO",
            Level::Debug | Level::Trace => "DEBUG",
        };
        let now = chrono::Local::now().format("%Y-%m-%d %H:%M:%S,%3f");
        eprintln!("{now} - {level} - {}", record.args());
    }

    fn flush(&self) {}
}

static LOGGER: StderrLogger = StderrLogger;

pub fn init(level: LevelFilter) {
    let _ = log::set_logger(&LOGGER);
    log::set_max_level(level);
}
