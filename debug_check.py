"""
정확한 문제 위치 파악
"""
import subprocess
from pathlib import Path

def get_first_pts(video_path):
    """첫 비디오 프레임의 PTS 확인"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts_time",
        "-of", "csv=p=0",
        "-read_intervals", "%+#1",
        video_path
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout.strip()

def check_file(path):
    if not Path(path).exists():
        return None
    pts = get_first_pts(path)
    print(f"  {Path(path).name}: 첫 PTS = {pts}")
    return pts

print("=" * 60)
print("🔍 중간 파일 첫 프레임 PTS 확인")
print("=" * 60)

# TMP 폴더 확인
tmp_dir = Path(".tmp_shuffle_merge")
if tmp_dir.exists():
    for folder in sorted(tmp_dir.iterdir()):
        if folder.is_dir():
            print(f"\n📁 {folder.name}/")
            for f in sorted(folder.glob("*.mp4")):
                check_file(str(f))

# 최종 출력 확인
print(f"\n📁 outputs/")
for f in Path("outputs/tiktok").glob("*.mp4"):
    check_file(str(f))

print("\n" + "=" * 60)
print("👆 PTS가 0.000000이 아닌 파일이 문제입니다!")
print("=" * 60)