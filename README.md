# 🎬 Koko Drama - Automated Video Merge Pipeline

한국 드라마 클립들을 자동으로 셔플/병합하여 TikTok 및 프로덕션용 비디오를 생성하는 배치 처리 시스템

## ✨ 주요 기능

- **상태 기반 배치 처리**: 200개+ 폴더를 자동으로 순회하며 처리
- **Cycle 시스템**: 7가지 Look Filter, Color Tint, Zoom/Speed Preset 자동 순환
- **멀티 버전 출력**: TikTok용 (인트로 포함) / Production용 (인트로 제외)
- **고급 비디오 처리**: Color Grading, Overlay Tinting, Dynamic Zoom, Speed Ramping
- **재현 가능**: 시드 기반 랜덤 셔플 + 상태 파일 추적

## 🛠️ 기술 스택

- Python 3.9+
- FFmpeg / FFprobe
- 표준 라이브러리만 사용 (외부 의존성 없음)

## 📂 디렉토리 구조

```
koko_drama/
├── shuffle_merge.py          # 메인 프로그램 (배치 처리)
├── gen_video.py              # 단일 폴더 처리 (구버전)
├── debug_check.py            # 디버그 유틸리티
│
├── dramas/                   # 입력 폴더 (200개+ 드라마 표현)
│   ├── 106니가/
│   ├── 100방금/
│   └── ...
│
├── intro_voices/             # 인트로 음성 파일들
├── outputs/
│   ├── tiktok/               # TikTok용 출력
│   └── production/           # 프로덕션용 출력
│
├── outro.mp4                 # 고정 아웃트로 비디오
├── cta_audio.MP3             # CTA 오디오
├── banner.png                # 배너 오버레이 이미지
└── sample_data/              # 테스트용 샘플
```

## 🚀 실행 방법

### 메인 프로그램 (상태 기반 배치 처리)

```bash
python shuffle_merge.py
```

- 한 번에 6개 폴더 처리 (PICK_FOLDERS_PER_RUN)
- 각 폴더에서 최대 3개 비디오 선택 (MAX_VIDEOS_PER_FOLDER)
- 처리 완료된 폴더는 `.koko_merge_state.json`에 기록
- 모든 폴더 완료 시 자동으로 다음 Cycle로 진행

### 단일 폴더 처리 (구버전)

```bash
python gen_video.py \
  --folder dramas/106니가 \
  --intro-audio intro_voices/intro.mp3 \
  --outro outro.mp4 \
  --output out.mp4 \
  --seed 42 \
  --max 10
```

## 🎨 Cycle 시스템

각 Cycle마다 자동으로 다른 스타일 적용:

### Look Filters (7가지)
- **clean**: 대비/채도 강화
- **warm**: 따뜻한 톤 (빨강/노랑)
- **cool**: 차가운 톤 (파랑)
- **soft**: 가우시안 블러
- **crisp**: 언샵 마스크
- **matte**: 영화 룩 (저대비/저채도)
- **grain**: 필름 그레인

### Overlay Tint Palette (7가지)
```
#00C2FF (사이버 블루)
#FF4D6D (핑크)
#22C55E (네온 그린)
#F59E0B (골드)
#A855F7 (퍼플)
#14B8A6 (터쿼이즈)
#EF4444 (레드)
```

### Zoom/Speed Presets (7가지)
- Preset A~G: 1.06~1.12x zoom, 1.02~1.07x speed

## 📝 비디오 파이프라인

```
입력 폴더
  ↓ 비디오 수집 & 셔플
  ↓ 최대 3개 선택
  ↓
전처리
  ↓ 첫 비디오 + intro_audio → intro 생성
  ↓ 각 비디오 정규화 (1080x1920, 30fps)
  ↓   ├─ 오버레이 적용 (overlay.png + tint)
  ↓   ├─ Look Filter 적용
  ↓   ├─ Zoom & Speed 적용
  ↓   └─ Banner 삽입 (2번째 클립부터)
  ↓
CTA 세그먼트
  ↓ 마지막 프레임 추출 + cta_audio.mp3
  ↓
병합
  ├─ TikTok: intro + clips + CTA + outro
  └─ Production: clips + CTA + outro
```

## ⚙️ 주요 설정 (shuffle_merge.py)

```python
PICK_FOLDERS_PER_RUN = 6        # 한 번에 처리할 폴더 수
MAX_VIDEOS_PER_FOLDER = 3       # 폴더당 선택할 비디오 수
TARGET_W = 1080                 # 출력 너비
TARGET_H = 1920                 # 출력 높이 (9:16 세로)
FORCE_FPS = 30.0                # 고정 프레임레이트
BASE_SEED = 42                  # 랜덤 시드
OVERLAY_TINT_STRENGTH = 0.85    # 오버레이 틴트 강도
```

## 📋 필수 요구사항

1. **FFmpeg 설치**: `ffmpeg`, `ffprobe` 명령어가 PATH에 있어야 함
2. **디렉토리 구조**: 
   - `dramas/` 폴더 내 각 서브폴더에 `.mp4` 파일 존재
   - `outro.mp4` 파일 존재
   - `intro_voices/intro.mp3` 또는 대체 인트로 오디오 존재
3. **선택 사항**:
   - `banner.png`: 배너 오버레이 (없으면 스킵)
   - `cta_audio.MP3`: CTA 세그먼트 (없으면 스킵)
   - 각 폴더 내 `overlay.png`: 폴더별 오버레이 (없으면 스킵)

## 🔧 상태 파일 (.koko_merge_state.json)

```json
{
  "cycle": 2,
  "done": ["100방금", "101근데", ...]
}
```

- **cycle**: 현재 사이클 번호 (Look/Tint/Preset 결정)
- **done**: 이미 처리된 폴더 이름 목록
- 모든 폴더 완료 시 `cycle += 1`, `done = []` 리셋

## 📦 출력 결과

### TikTok 버전 (`outputs/tiktok/v1_tiktok.mp4`)
- Intro (첫 비디오 클립 + 인트로 음성)
- 메인 클립들 (배너 오버레이 포함)
- CTA 세그먼트 (마지막 프레임 + CTA 오디오)
- Outro 비디오

### Production 버전 (`outputs/production/v1_production.mp4`)
- 메인 클립들 (배너 오버레이 없음)
- CTA 세그먼트
- Outro 비디오

## 🐛 디버깅

```bash
# 특정 폴더 수동 처리 (테스트용)
python gen_video.py --folder dramas/테스트폴더 --intro-audio intro.mp3 --outro outro.mp4 --output test.mp4

# 상태 파일 리셋
rm .koko_merge_state.json

# 임시 파일 정리
rm -rf .tmp_shuffle_merge tmp
```

## 📄 라이선스

MIT License

## 👤 Author

jaeone3
