//! 스크롤 캡처: 휠을 한 칸씩 굴릴 때마다 찍은 화면을, 겹치는 줄을 찾아 한 장으로 잇는다.
//!
//! - 그림은 위에서 아래로 쌓은 BGRA(한 점 4바이트) 줄이다.
//! - 줄마다 '요약'(가로를 64칸으로 나눈 칸별 밝기 평균)을 내어 비교한다. 화면 배율이 100%가 아니면 굴린 뒤
//!   글자 가장자리 색이 1~2 씩 달라져 점 하나하나로는 같은 줄이 다르게 나온다(실제 PC 시험에서 확인).
//!   칸별 평균이 4 이내로 같으면 같은 줄로 본다.
//! - 앞 장의 아래쪽 줄과 새 장의 위쪽 줄이 가장 잘 맞는 어긋남(d)을 찾고, 새 장의 맨 아래 d 줄만 덧붙인다.
//! - 위아래에 고정된 띠(웹의 메뉴 띠, 한글·엑셀의 머리 줄 등)는 굴려도 그대로라 처음 두 장을 비교해 찾는다.
//!   맨 위 띠는 첫 장에서 한 번, 맨 아래 띠는 마지막 장에서 한 번만 남긴다.
//! - 한 가지 색으로만 된 줄(빈 줄)은 어디와도 맞으므로 맞는 정도를 셀 때 빼고 센다.
//!
//! 이 파일은 Windows 를 쓰지 않는다(리눅스에서도 시험을 돌릴 수 있다).

/// 굴렸을 때 새 장과 앞 장을 비교한 결과
#[derive(Debug, PartialEq, Eq)]
pub enum Push {
    /// d 줄을 새로 덧붙였다
    Added(usize),
    /// 화면이 그대로다(끝까지 내려갔거나 휠이 먹지 않았다)
    Same,
    /// 겹치는 곳을 찾지 못했다(화면이 크게 바뀌었다). 여기서 멈춘다.
    NoMatch,
}

pub struct Stitcher {
    width: usize,
    height: usize,
    /// 고정된 맨 위·맨 아래 띠의 줄 수(첫 비교에서 정한다)
    top: usize,
    bottom: usize,
    fixed_known: bool,
    /// 지금까지 이은 그림(맨 아래 띠는 아직 넣지 않았다)
    out: Vec<u8>,
    prev: Vec<u8>,
    prev_sig: Vec<[u8; BLOCKS]>,
    prev_info: Vec<bool>,
    last_shift: Option<usize>,
    /// 마지막에 잘라 낼 왼쪽·오른쪽 가장자리 열(굴릴 때마다 움직인 스크롤 막대)
    cut_left: usize,
    cut_right: usize,
}

/// 줄 요약의 칸 수
const BLOCKS: usize = 64;
/// 칸별 밝기 평균이 이만큼 이내면 같은 줄로 본다
const TOLERANCE: u8 = 4;

/// 줄 하나의 요약: 가로를 BLOCKS 칸으로 나눈 칸별 밝기 평균
fn row_sig(row: &[u8], width: usize) -> [u8; BLOCKS] {
    let mut sig = [0u8; BLOCKS];
    let blocks = BLOCKS.min(width);
    for (i, slot) in sig.iter_mut().enumerate().take(blocks) {
        let (from, to) = (i * width / blocks, ((i + 1) * width / blocks).max(i * width / blocks + 1));
        let mut sum = 0u32;
        for px in row[from * 4..to * 4].chunks_exact(4) {
            sum += px[0] as u32 + px[1] as u32 + px[2] as u32;
        }
        *slot = (sum / (3 * (to - from) as u32)) as u8;
    }
    sig
}

/// 한 가지 색으로만 된 줄이 아니면 참(비교에 쓸 만한 줄)
fn informative(row: &[u8]) -> bool {
    let first = &row[..3];
    row.chunks_exact(4).any(|px| &px[..3] != first)
}

/// 칸 대부분이 같으면 같은 줄로 본다. 가장자리의 스크롤 막대처럼 굴릴 때마다 움직이는 좁은 세로 띠가
/// 칸 한두 개를 바꾸므로 2칸까지는 달라도 된다(실제 PC 시험에서 확인).
fn close(a: &[u8; BLOCKS], b: &[u8; BLOCKS]) -> bool {
    a.iter().zip(b).filter(|(x, y)| x.abs_diff(**y) > TOLERANCE).count() <= 2
}

fn distance(a: &[u8; BLOCKS], b: &[u8; BLOCKS]) -> u32 {
    a.iter().zip(b).map(|(x, y)| x.abs_diff(*y) as u32).sum()
}

fn analyse(frame: &[u8], width: usize) -> (Vec<[u8; BLOCKS]>, Vec<bool>) {
    let stride = width * 4;
    frame
        .chunks_exact(stride)
        .map(|row| (row_sig(row, width), informative(row)))
        .unzip()
}

impl Stitcher {
    pub fn new(first: Vec<u8>, width: usize, height: usize) -> Self {
        let (sig, info) = analyse(&first, width);
        Self {
            width,
            height,
            top: 0,
            bottom: 0,
            fixed_known: false,
            out: first.clone(),
            prev: first,
            prev_sig: sig,
            prev_info: info,
            last_shift: None,
            cut_left: 0,
            cut_right: 0,
        }
    }

    /// 지금까지 이은 그림의 높이(마지막에 붙일 맨 아래 띠 포함)
    pub fn height(&self) -> usize {
        self.out.len() / (self.width * 4) + if self.fixed_known { self.bottom } else { 0 }
    }

    pub fn push(&mut self, frame: Vec<u8>) -> Push {
        let (w, h) = (self.width, self.height);
        let stride = w * 4;
        debug_assert_eq!(frame.len(), stride * h);
        let (sig, info) = analyse(&frame, w);
        let same_row = |y: usize| close(&sig[y], &self.prev_sig[y]);
        if (0..h).all(same_row) {
            return Push::Same;
        }
        let (top, bottom) = if self.fixed_known {
            (self.top, self.bottom)
        } else {
            let top = (0..h).take_while(|&y| same_row(y)).count();
            let bottom = (0..h).rev().take_while(|&y| same_row(y)).count();
            // 바뀐 곳이 아주 좁으면(깜박이는 글자 커서 등) 굴러간 것이 아니다
            if top + bottom + 16 >= h {
                return Push::Same;
            }
            (top.min(h / 3), bottom.min(h / 3))
        };
        let content = h - top - bottom;
        let min_overlap = (content / 8).max(12).min(content.saturating_sub(1));
        if content <= min_overlap {
            return Push::NoMatch;
        }

        // 어긋남 d 후보마다 앞 장의 [top+d ..] 와 새 장의 [top ..] 을 맞춰 본다
        // (d, 맞은 비율, 줄당 평균 차이)
        let mut candidates: Vec<(usize, f64, f64)> = Vec::new();
        for d in 1..=content - min_overlap {
            let overlap = content - d;
            let (mut inf, mut hit, mut all_hit, mut dist) = (0usize, 0usize, 0usize, 0u64);
            for i in 0..overlap {
                let a = top + i + d;
                let b = top + i;
                let same = close(&self.prev_sig[a], &sig[b]);
                if same {
                    all_hit += 1;
                }
                if self.prev_info[a] || info[b] {
                    inf += 1;
                    dist += distance(&self.prev_sig[a], &sig[b]) as u64;
                    if same {
                        hit += 1;
                    }
                }
            }
            let need = 8.min(overlap / 4).max(1);
            if inf < need {
                continue;
            }
            let ratio = hit as f64 / inf as f64;
            let all_ratio = all_hit as f64 / overlap as f64;
            if ratio >= 0.9 && all_ratio >= 0.9 {
                candidates.push((d, ratio, dist as f64 / inf as f64));
            }
        }
        if candidates.is_empty() {
            return Push::NoMatch;
        }
        let best = candidates.iter().map(|c| c.1).fold(0.0, f64::max);
        let good: Vec<&(usize, f64, f64)> = candidates.iter().filter(|c| c.1 >= best - 0.01).collect();
        // 같은 무늬가 되풀이되면(빈 표 등) 여러 d 가 다 맞는다. 앞 단계에서 굴러간 만큼에 가장 가까운 것,
        // 처음이면 차이가 가장 작은 것을 고른다.
        let d = match self.last_shift {
            Some(last) => good.iter().min_by_key(|c| c.0.abs_diff(last)).unwrap().0,
            None => good.iter().min_by(|x, y| x.2.total_cmp(&y.2)).unwrap().0,
        };

        self.find_moving_edges(&frame, top, content, d);
        if !self.fixed_known {
            self.top = top;
            self.bottom = bottom;
            self.fixed_known = true;
            // 첫 장의 맨 아래 띠는 마지막에 한 번만 붙인다
            let keep = self.out.len() - bottom * stride;
            self.out.truncate(keep);
        }
        let from = (top + content - d) * stride;
        let to = (top + content) * stride;
        self.out.extend_from_slice(&frame[from..to]);
        self.prev = frame;
        self.prev_sig = sig;
        self.prev_info = info;
        self.last_shift = Some(d);
        Push::Added(d)
    }

    /// 맞춘 두 장에서 가장자리 열 가운데 내용이 다른 곳(스크롤 막대의 손잡이)을 찾아 잘라 낼 폭을 늘린다.
    /// 가장자리 1/12 안에서만 찾는다(그 안쪽은 내용이다).
    fn find_moving_edges(&mut self, frame: &[u8], top: usize, content: usize, d: usize) {
        let (w, stride) = (self.width, self.width * 4);
        let overlap = content - d;
        let zone = w / 12;
        if zone == 0 || overlap == 0 {
            return;
        }
        let bad = |x: usize| -> bool {
            let mut differ = 0usize;
            for i in 0..overlap {
                let a = (top + i + d) * stride + x * 4;
                let b = (top + i) * stride + x * 4;
                let diff: u32 = (0..3).map(|c| self.prev[a + c].abs_diff(frame[b + c]) as u32).sum();
                if diff > 30 {
                    differ += 1;
                }
            }
            differ * 20 > overlap // 5% 넘는 줄에서 다르면
        };
        if let Some(x) = (w - zone..w).find(|&x| bad(x)) {
            self.cut_right = self.cut_right.max(w - x);
        }
        if let Some(x) = (0..zone).rev().find(|&x| bad(x)) {
            self.cut_left = self.cut_left.max(x + 1);
        }
    }

    /// 다 이은 그림(너비, 높이, BGRA)
    pub fn finish(mut self) -> (usize, usize, Vec<u8>) {
        let stride = self.width * 4;
        if self.fixed_known && self.bottom > 0 {
            let from = (self.height - self.bottom) * stride;
            let footer = self.prev[from..].to_vec();
            self.out.extend_from_slice(&footer);
        }
        let h = self.out.len() / stride;
        if self.cut_left + self.cut_right == 0 || self.cut_left + self.cut_right >= self.width {
            return (self.width, h, self.out);
        }
        let nw = self.width - self.cut_left - self.cut_right;
        let mut cut = Vec::with_capacity(nw * h * 4);
        for row in self.out.chunks_exact(stride) {
            cut.extend_from_slice(&row[self.cut_left * 4..(self.cut_left + nw) * 4]);
        }
        (nw, h, cut)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 긴 문서(줄마다 다른 무늬)를 만든다. y 줄의 x 점 색은 (y*7 + x) 등으로 정한다.
    fn page(width: usize, height: usize) -> Vec<u8> {
        let mut v = Vec::with_capacity(width * height * 4);
        for y in 0..height {
            for x in 0..width {
                // 몇 줄마다 빈 줄(한 색)을 넣어 실제 문서처럼
                if y % 9 == 4 {
                    v.extend_from_slice(&[255, 255, 255, 255]);
                } else {
                    v.extend_from_slice(&[(y * 7 % 251) as u8, ((x * 3 + y) % 253) as u8, (x * y % 241) as u8, 255]);
                }
            }
        }
        v
    }

    /// 문서의 offset 줄부터 view 줄을 보여 주는 화면. 위 header 줄·아래 footer 줄은 고정 띠.
    fn view(doc: &[u8], width: usize, offset: usize, view: usize, header: usize, footer: usize) -> Vec<u8> {
        let stride = width * 4;
        let mut v = Vec::new();
        for y in 0..header {
            v.extend(std::iter::repeat([10u8, 20, (y * 5) as u8, 255]).take(width).flatten());
        }
        let body = view - header - footer;
        v.extend_from_slice(&doc[offset * stride..(offset + body) * stride]);
        for y in 0..footer {
            v.extend(std::iter::repeat([200u8, (y * 9) as u8, 30, 255]).take(width).flatten());
        }
        v
    }

    #[test]
    fn stitches_scrolled_document_with_fixed_bars() {
        let (w, doc_h, vh, header, footer, step) = (40, 900, 200, 24, 10, 37);
        let doc = page(w, doc_h);
        let body = vh - header - footer;
        let mut st = Stitcher::new(view(&doc, w, 0, vh, header, footer), w, vh);
        let mut offset = 0;
        loop {
            let next = (offset + step).min(doc_h - body);
            let r = st.push(view(&doc, w, next, vh, header, footer));
            if next == offset {
                assert_eq!(r, Push::Same);
                break;
            }
            assert!(matches!(r, Push::Added(_)), "{r:?}");
            offset = next;
        }
        let (rw, rh, out) = st.finish();
        assert_eq!(rw, w);
        assert_eq!(rh, header + doc_h + footer);
        let expect = {
            let v0 = view(&doc, w, 0, vh, header, footer);
            let mut e = v0[..header * w * 4].to_vec();
            e.extend_from_slice(&doc);
            e.extend_from_slice(&v0[(vh - footer) * w * 4..]);
            e
        };
        assert!(out == expect);
    }

    /// 화면 배율 때문에 굴릴 때마다 점 색이 1~2 씩 달라지고, 오른쪽 스크롤 막대 손잡이가 움직이는 경우
    #[test]
    fn tolerates_noise_and_cuts_moving_scrollbar() {
        let (w, doc_h, vh, step, bar) = (400usize, 700usize, 160usize, 29usize, 10usize);
        let doc = page(w, doc_h);
        let stride = w * 4;
        let mut seed = 7u32;
        let mut frame = |offset: usize| -> Vec<u8> {
            let mut v = doc[offset * stride..(offset + vh) * stride].to_vec();
            for px in v.chunks_exact_mut(4) {
                seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
                let n = (seed >> 16) % 3; // 0..2 만큼 흔들기
                px[0] = px[0].saturating_add(n as u8);
            }
            // 오른쪽 bar 칸: 손잡이(검정)가 문서 위치에 따라 내려간다
            let thumb = offset * vh / doc_h;
            for y in 0..vh {
                for x in w - bar..w {
                    let i = y * stride + x * 4;
                    let c = if y >= thumb && y < thumb + 30 { 20 } else { 240 };
                    v[i..i + 3].copy_from_slice(&[c, c, c]);
                }
            }
            v
        };
        let mut st = Stitcher::new(frame(0), w, vh);
        let mut offset = 0;
        loop {
            let next = (offset + step).min(doc_h - vh);
            let r = st.push(frame(next));
            if next == offset {
                assert_eq!(r, Push::Same);
                break;
            }
            assert_eq!(r, Push::Added(next - offset));
            offset = next;
        }
        let (rw, rh, _) = st.finish();
        assert_eq!(rh, doc_h);
        assert_eq!(rw, w - bar);
    }

    #[test]
    fn same_when_nothing_moves() {
        let w = 30;
        let doc = page(w, 300);
        let first = view(&doc, w, 0, 120, 0, 0);
        let mut st = Stitcher::new(first.clone(), w, 120);
        assert_eq!(st.push(first), Push::Same);
        let (_, h, _) = st.finish();
        assert_eq!(h, 120);
    }

    #[test]
    fn no_match_when_screen_changes_completely() {
        let w = 30;
        let doc = page(w, 2000);
        let mut st = Stitcher::new(view(&doc, w, 0, 120, 0, 0), w, 120);
        assert_eq!(st.push(view(&doc, w, 900, 120, 0, 0)), Push::NoMatch);
    }
}
