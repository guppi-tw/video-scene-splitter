"""
ffmpegによるサムネイル生成・動画分割
"""
import subprocess
import shutil
from pathlib import Path
from typing import Callable, Optional
import platform


class FFmpegRunner:
    """ffmpeg操作クラス"""
    
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
        self._current_process: Optional[subprocess.Popen] = None
        self._cancelled = False
    
    def _find_ffmpeg(self) -> str:
        """ffmpegのパスを探す"""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        
        # Windows用の一般的なパス
        if platform.system() == "Windows":
            common_paths = [
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
            ]
            for p in common_paths:
                if p.exists():
                    return str(p)
        
        raise RuntimeError("ffmpegが見つかりません。PATHに追加してください。")
    
    def cancel(self):
        """現在の処理をキャンセル"""
        self._cancelled = True
        if self._current_process:
            self._current_process.terminate()
    
    def reset_cancel(self):
        """キャンセル状態をリセット"""
        self._cancelled = False
    
    def generate_thumbnail(
        self,
        video_path: Path,
        time_sec: float,
        output_path: Path,
        width: int = 320,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        指定時刻のサムネイルを生成
        
        Args:
            video_path: 動画ファイルパス
            time_sec: 切り出し時刻（秒）
            output_path: 出力画像パス
            width: サムネイル幅
            progress_callback: 進捗コールバック
            
        Returns:
            成功したかどうか
        """
        if self._cancelled:
            return False
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", str(time_sec),
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", f"scale={width}:-1",
            str(output_path)
        ]
        
        if progress_callback:
            progress_callback(f"サムネイル生成: {time_sec:.2f}秒")
        
        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            _, stderr = self._current_process.communicate(timeout=30)
            self._current_process = None
            
            if output_path.exists():
                return True
            else:
                if progress_callback:
                    progress_callback(f"サムネイル生成失敗: {stderr.decode('utf-8', errors='ignore')}")
                return False
                
        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
            self._current_process = None
            return False
        except Exception as e:
            if progress_callback:
                progress_callback(f"エラー: {str(e)}")
            self._current_process = None
            return False
    
    def extract_clip(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        output_path: Path,
        use_copy: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        動画からクリップを切り出し
        
        Args:
            video_path: 入力動画パス
            start_time: 開始時刻（秒）
            end_time: 終了時刻（秒）
            output_path: 出力パス
            use_copy: コーデックコピーを使用するか
            progress_callback: 進捗コールバック
            
        Returns:
            成功したかどうか
        """
        if self._cancelled:
            return False
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        duration = end_time - start_time
        
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration),
        ]
        
        if use_copy:
            cmd.extend(["-c", "copy"])
        else:
            cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
        
        cmd.append(str(output_path))
        
        if progress_callback:
            progress_callback(f"クリップ書き出し: {start_time:.2f}s - {end_time:.2f}s ({duration:.2f}s)")
        
        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            _, stderr = self._current_process.communicate()
            self._current_process = None
            
            if output_path.exists() and output_path.stat().st_size > 0:
                if progress_callback:
                    progress_callback(f"完了: {output_path.name}")
                return True
            else:
                if progress_callback:
                    progress_callback(f"書き出し失敗: {stderr.decode('utf-8', errors='ignore')[:200]}")
                return False
                
        except Exception as e:
            if progress_callback:
                progress_callback(f"エラー: {str(e)}")
            self._current_process = None
            return False
    
    def get_video_duration(self, video_path: Path) -> Optional[float]:
        """動画の長さを取得"""
        cmd = [
            self.ffmpeg_path,
            "-i", str(video_path),
            "-f", "null", "-"
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60
            )
            # ffmpegはstderrに情報を出力する
            output = result.stderr.decode('utf-8', errors='ignore')
            
            # Duration: HH:MM:SS.ms を探す
            import re
            match = re.search(r'Duration: (\d+):(\d+):(\d+)\.(\d+)', output)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                ms = int(match.group(4))
                return hours * 3600 + minutes * 60 + seconds + ms / 100
            return None
            
        except Exception:
            return None
