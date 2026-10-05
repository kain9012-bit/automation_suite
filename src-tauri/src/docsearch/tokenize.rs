//! 한국어 낱말 나누기(Lindera + mecab-ko-dic). 도큐파인더와 같은 방식이다.
//!
//! 색인과 검색어를 같은 방식으로 나눠야 서로 맞는다. 조사(J…)·어미(E…)·접사(X…)·
//! 부호(S… 중 글자 아닌 것)는 빼고, 명사·동사 어간·숫자·영문·한자 등만 남긴다.
//! 예: "학교예산을 편성하여" → 학교 예산 편성

use lindera::dictionary::load_dictionary;
use lindera::mode::Mode;
use lindera::segmenter::Segmenter;
use lindera::tokenizer::Tokenizer;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// 사전을 펼치면 메모리를 200MB 넘게 쓴다(실측 약 220MB). JB업무ON 은 트레이에 늘 떠 있으므로
/// 검색·색인에 쓸 때만 펼치고, 3분 동안 안 쓰면 내려놓는다. 다시 펼치는 데는 1초도 안 걸린다.
const IDLE_RELEASE: Duration = Duration::from_secs(180);

struct Loaded {
    tokenizer: Arc<Tokenizer>,
    last_used: Instant,
}

static TOKENIZER: Mutex<Option<Loaded>> = Mutex::new(None);
static REAPER_STARTED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn tokenizer() -> Option<Arc<Tokenizer>> {
    let mut slot = TOKENIZER.lock().ok()?;
    if let Some(loaded) = slot.as_mut() {
        loaded.last_used = Instant::now();
        return Some(loaded.tokenizer.clone());
    }
    let dict = load_dictionary("embedded://ko-dic").ok()?;
    let tokenizer = Arc::new(Tokenizer::new(Segmenter::new(Mode::Normal, dict, None)));
    *slot = Some(Loaded { tokenizer: tokenizer.clone(), last_used: Instant::now() });
    start_reaper();
    Some(tokenizer)
}

/// 오래 안 쓴 사전을 내려놓는 감시 스레드(하나만).
fn start_reaper() {
    if REAPER_STARTED.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    std::thread::spawn(|| loop {
        std::thread::sleep(Duration::from_secs(30));
        if let Ok(mut slot) = TOKENIZER.lock() {
            if slot.as_ref().map(|l| l.last_used.elapsed() > IDLE_RELEASE).unwrap_or(false) {
                *slot = None; // 쓰는 중인 곳이 있으면 그쪽이 다 쓴 뒤에 풀린다(Arc)
            }
        }
    });
}

fn keep_pos(pos: &str) -> bool {
    // 조사·어미·접사·서술격 조사
    if pos.starts_with('J') || pos.starts_with('E') || pos.starts_with('X') || pos.starts_with("VC") {
        return false;
    }
    // 부호: 외국어(SL)·한자(SH)·숫자(SN)만 남긴다
    if pos.starts_with('S') {
        return matches!(pos, "SL" | "SH" | "SN");
    }
    true
}

/// 낱말로 쓸 수 있는 글자만 남기고 소문자로
fn clean(term: &str) -> String {
    term.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

/// 글 한 덩어리를 낱말 목록으로. 사전을 못 불러오면 띄어쓰기로만 나눈다.
pub fn terms(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let Some(tk) = tokenizer() else {
        return text.split_whitespace().map(clean).filter(|t| !t.is_empty()).collect();
    };
    // 긴 글을 통째로 넣지 않고 줄 단위로 나눈다(분석 표가 커지지 않게).
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(mut tokens) = tk.tokenize(line) else {
            out.extend(line.split_whitespace().map(clean).filter(|t| !t.is_empty()));
            continue;
        };
        for token in tokens.iter_mut() {
            let surface = token.surface.to_string();
            let pos = token.details().first().map(|p| p.to_string()).unwrap_or_default();
            if !keep_pos(&pos) {
                continue;
            }
            let term = clean(&surface);
            if !term.is_empty() {
                out.push(term);
            }
        }
    }
    out
}

/// 색인에 넣을 글: 낱말을 띄어쓰기로 이은 것.
/// 서식 제목처럼 한 글자씩 띄어 쓴 말("안 건 처 리 상 황 표", "성 명")은 붙인 꼴도 함께 넣어
/// "안건처리상황표", "성명"으로 찾히게 한다.
pub fn index_text(text: &str) -> String {
    let mut all = text.to_string();
    for joined in spaced_words(text) {
        all.push('\n');
        all.push_str(&joined);
    }
    terms(&all).join(" ")
}

fn is_syllable(c: char) -> bool {
    ('가'..='힣').contains(&c)
}

/// 한 글자짜리 한글이 띄어쓰기로 두 개 이상 이어진 것을 붙인 말들
fn spaced_words(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    for line in text.lines() {
        let mut run = String::new();
        let mut count = 0;
        for word in line.split_whitespace().chain(std::iter::once("")) {
            // "명:" 처럼 끝에 붙은 부호는 떼고 본다. 부호가 붙어 있으면 거기서 끊는다.
            let core = word.trim_matches(|c: char| !c.is_alphanumeric());
            let mut chars = core.chars();
            let single = matches!((chars.next(), chars.next()), (Some(c), None) if is_syllable(c));
            if single {
                run.push_str(core);
                count += 1;
            }
            if !single || core.len() != word.len() {
                if count >= 2 {
                    out.push(std::mem::take(&mut run));
                }
                run.clear();
                count = 0;
            }
        }
    }
    out
}

/// 사전을 미리 불러 둔다(처음 검색이 느리지 않게).
pub fn warm_up() {
    let _ = tokenizer();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drops_particles_and_endings() {
        let t = terms("학교예산을 편성하여 집행하는 절차");
        assert!(t.contains(&"학교".to_string()), "{t:?}");
        assert!(t.contains(&"예산".to_string()), "{t:?}");
        assert!(t.contains(&"편성".to_string()), "{t:?}");
        assert!(t.contains(&"절차".to_string()), "{t:?}");
        assert!(!t.contains(&"을".to_string()), "{t:?}");
        assert!(!t.contains(&"여".to_string()), "{t:?}");
    }

    #[test]
    fn spaced_titles_are_joined() {
        assert_eq!(spaced_words("안 건 처 리 상 황 표\n성 명: 홍길동"), vec!["안건처리상황표", "성명"]);
        let idx = index_text("안 건 처 리 상 황 표");
        for t in terms("안건처리상황표") {
            assert!(idx.split(' ').any(|x| x == t), "{t} in {idx}");
        }
    }

    #[test]
    fn same_terms_for_query_and_document() {
        // 검색어 "예산"이 문서의 "학교예산을"에서 나온 낱말과 맞아야 한다.
        assert_eq!(terms("예산"), vec!["예산".to_string()]);
        let doc = terms("2026학년도 학교예산을 HACCP 기준으로");
        assert!(doc.contains(&"예산".to_string()));
        assert!(doc.contains(&"haccp".to_string()), "{doc:?}");
        assert!(doc.contains(&"2026".to_string()), "{doc:?}");
    }
}

#[cfg(test)]
mod mem {
    #[test]
    #[ignore]
    fn rss_after_warm_up() {
        let rss = || std::fs::read_to_string("/proc/self/status").unwrap().lines().find(|l| l.starts_with("VmRSS")).unwrap().to_string();
        println!("before {}", rss());
        let t = std::time::Instant::now();
        super::warm_up();
        println!("after {} in {:?}", rss(), t.elapsed());
        let t = std::time::Instant::now();
        let n = super::terms(&"학교예산을 편성하여 집행하는 절차를 안내합니다. ".repeat(2000)).len();
        println!("tokens {n} in {:?}, {}", t.elapsed(), rss());
    }
}
