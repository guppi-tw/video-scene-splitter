"""
ffmpegによるサムネイル生成・動画分割
"""
import logging
import subprocess
import sys
import shutil
from datetime import date
from pathlib import Path
from typing import Callable, Optional
import platform


def _popen_kwargs() -> dict:
    """Windows でコンソールウィンドウを表示しない Popen 用の kwargs を返す"""
    kwargs = {}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs

logger = logging.getLogger(__name__)


def _binary_name(base_name: str) -> str:
    """Return the platform-specific executable name."""
    if platform.system() == "Windows":
        return f"{base_name}.exe"
    return base_name


def _project_root() -> Path:
    # app/core/ffmpeg_runner.py -> app/core -> app -> project_root
    return Path(__file__).resolve().parent.parent.parent


def _pyinstaller_roots() -> list[Path]:
    """Return likely PyInstaller data roots for onefile, onedir, and macOS .app builds."""
    roots: list[Path] = []

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        roots.append(executable_dir)

        if hasattr(sys, "_MEIPASS"):
            roots.append(Path(sys._MEIPASS).resolve())

        # macOS .app bundles commonly place PyInstaller data under Contents/Frameworks,
        # while some layouts or specs use Contents/Resources.
        for parent in executable_dir.parents:
            if parent.name == "Contents":
                roots.extend([parent / "Frameworks", parent / "Resources"])
                break

    return roots


def _candidate_bundled_binary_paths(binary_name: str) -> list[Path]:
    """Return bundled binary candidates in source and PyInstaller layouts."""
    candidates: list[Path] = [
        _project_root() / "vendor" / "ffmpeg" / binary_name,
    ]

    for root in _pyinstaller_roots():
        candidates.extend(
            [
                root / "vendor" / "ffmpeg" / binary_name,
                root / "ffmpeg" / binary_name,
                root / binary_name,
            ]
        )

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(candidates))


def get_bundled_ffmpeg_path() -> Optional[Path]:
    """
    同梱されたffmpegバイナリのパスを取得
    
    Returns:
        ffmpegバイナリのパス、存在しない場合はNone
    """
    ffmpeg_name = _binary_name("ffmpeg")
    for candidate in _candidate_bundled_binary_paths(ffmpeg_name):
        if candidate.exists():
            return candidate
    
    return None


class FFmpegRunner:
    """ffmpeg操作クラス"""
    
    # クリップ書き出し（コーデックコピー）の最大待ち時間
    EXTRACT_TIMEOUT_SEC = 3600

    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
        self.ffprobe_path = self._find_ffprobe()
        self._current_process: Optional[subprocess.Popen] = None
        self._cancelled = False
    
    def _find_ffmpeg(self) -> str:
        """
        ffmpegのパスを探す
        
        優先順位:
        1. 同梱バイナリ (vendor/ffmpeg/)
        2. システムPATH
        3. Windows一般的なパス
        """
        # 1. 同梱バイナリを確認
        bundled = get_bundled_ffmpeg_path()
        if bundled:
            return str(bundled)
        
        # 2. システムPATHから探す
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        
        # 3. Windows用の一般的なパス
        if platform.system() == "Windows":
            common_paths = [
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
                Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe",
            ]
            for p in common_paths:
                if p.exists():
                    return str(p)
        
        raise RuntimeError(
            "ffmpegが見つかりません。\n"
            "以下のいずれかを実行してください:\n"
            "1. python scripts/setup_ffmpeg.py を実行してffmpegをダウンロード\n"
            "2. ffmpegをインストールしてPATHに追加"
        )
    
    def _find_ffprobe(self) -> Optional[str]:
        """ffprobeのパスを探す（ffmpegの隣 → システムPATH）"""
        sibling = Path(self.ffmpeg_path).parent / _binary_name("ffprobe")
        if sibling.exists():
            return str(sibling)
        return shutil.which("ffprobe")

    @property
    def is_bundled(self) -> bool:
        """同梱バイナリを使用しているかどうか"""
        bundled = get_bundled_ffmpeg_path()
        return bundled is not None and str(bundled) == self.ffmpeg_path

    def cancel(self):
        """現在の処理をキャンセル"""
        self._cancelled = True
        # ワーカースレッド側で None に差し替えられる可能性があるためローカルに取る
        process = self._current_process
        if process:
            try:
                process.terminate()
            except OSError:
                pass
    
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
                stderr=subprocess.PIPE,
                **_popen_kwargs()
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
            logger.warning(f"サムネイル生成がタイムアウト: {video_path} at {time_sec}s")
            if self._current_process:
                self._current_process.kill()
            self._current_process = None
            return False
        except FileNotFoundError as e:
            logger.error(f"ffmpegが見つかりません: {e}")
            if progress_callback:
                progress_callback(f"エラー: ffmpegが見つかりません")
            self._current_process = None
            return False
        except OSError as e:
            logger.error(f"サムネイル生成中にOSエラー: {video_path}: {e}")
            if progress_callback:
                progress_callback(f"エラー: {e}")
            self._current_process = None
            return False

    def extract_frame(
        self,
        video_path: Path,
        time_sec: float,
        output_path: Path,
        video_filter: Optional[str] = None,
    ) -> bool:
        """指定時刻のフレームを1枚書き出す（OCR等の解析用、スケールしない）

        Args:
            video_filter: 任意のffmpeg -vf フィルタ（クロップ・拡大など）
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
        ]
        if video_filter:
            cmd.extend(["-vf", video_filter])
        cmd.append(str(output_path))

        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_popen_kwargs()
            )
            self._current_process.communicate(timeout=30)
            self._current_process = None
            return output_path.exists()
        except subprocess.TimeoutExpired:
            logger.warning(f"フレーム抽出がタイムアウト: {video_path} at {time_sec}s")
            if self._current_process:
                self._current_process.kill()
            self._current_process = None
            return False
        except (FileNotFoundError, OSError) as e:
            logger.error(f"フレーム抽出に失敗: {video_path}: {e}")
            self._current_process = None
            return False

    def extract_clip(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        output_path: Path,
        use_copy: bool = True,
        creation_date: Optional[date] = None,
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
            creation_date: コンテナの作成日時メタデータに書き込む日付
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
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
            ])

        if creation_date is not None:
            cmd.extend([
                "-metadata",
                f"creation_time={creation_date.isoformat()}T00:00:00",
            ])

        cmd.append(str(output_path))
        
        if progress_callback:
            progress_callback(f"クリップ書き出し: {start_time:.2f}s - {end_time:.2f}s ({duration:.2f}s)")
        
        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_popen_kwargs()
            )
            _, stderr = self._current_process.communicate(timeout=self.EXTRACT_TIMEOUT_SEC)
            self._current_process = None
            
            if output_path.exists() and output_path.stat().st_size > 0:
                if progress_callback:
                    progress_callback(f"完了: {output_path.name}")
                return True
            else:
                if progress_callback:
                    progress_callback(f"書き出し失敗: {stderr.decode('utf-8', errors='ignore')[:200]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning(f"クリップ書き出しがタイムアウト: {video_path}")
            if self._current_process:
                self._current_process.kill()
            self._current_process = None
            if progress_callback:
                progress_callback("エラー: 書き出しがタイムアウトしました")
            return False
        except FileNotFoundError as e:
            logger.error(f"ffmpegが見つかりません: {e}")
            if progress_callback:
                progress_callback("エラー: ffmpegが見つかりません")
            self._current_process = None
            return False
        except OSError as e:
            logger.error(f"クリップ書き出し中にOSエラー: {video_path}: {e}")
            if progress_callback:
                progress_callback(f"エラー: {e}")
            self._current_process = None
            return False

    def detect_silence(
        self,
        video_path: Path,
        duration: float,
        noise_db: int = -35,
        minimum_duration: float = 1.0,
    ) -> list[tuple[float, float]]:
        """音声の無音区間を FFmpeg の silencedetect で検出する。"""
        if self._cancelled:
            return []
        cmd = [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostats",
            "-i", str(video_path),
            "-vn",
            "-af", f"silencedetect=noise={noise_db}dB:d={minimum_duration}",
            "-f", "null",
            "-",
        ]
        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_popen_kwargs(),
            )
            _stdout, stderr = self._current_process.communicate(
                timeout=self.EXTRACT_TIMEOUT_SEC
            )
            self._current_process = None
            from app.core.media_signal_detector import parse_silencedetect_output

            return parse_silencedetect_output(
                stderr.decode("utf-8", errors="ignore"), duration
            )
        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
            self._current_process = None
            return []
        except (FileNotFoundError, OSError):
            self._current_process = None
            return []

    def get_video_duration(self, video_path: Path) -> Optional[float]:
        """動画の長さを取得（ffprobe優先、なければffmpegのヘッダ出力から解析）"""
        try:
            if self.ffprobe_path:
                result = subprocess.run(
                    [
                        self.ffprobe_path,
                        "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(video_path),
                    ],
                    capture_output=True,
                    timeout=30,
                    **_popen_kwargs()
                )
                output = result.stdout.decode('utf-8', errors='ignore').strip()
                try:
                    return float(output)
                except ValueError:
                    logger.warning(f"ffprobeの出力を解析できません: {video_path}: {output!r}")

            # フォールバック: 出力先を指定せず実行するとffmpegは
            # ファイル情報だけ表示して即終了する（デコードはしない）
            result = subprocess.run(
                [self.ffmpeg_path, "-i", str(video_path)],
                capture_output=True,
                timeout=30,
                **_popen_kwargs()
            )
            # ffmpegはstderrに情報を出力する
            output = result.stderr.decode('utf-8', errors='ignore')

            # Duration: HH:MM:SS.cc を探す
            import re
            match = re.search(r'Duration: (\d+):(\d+):(\d+)\.(\d+)', output)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                centisec = int(match.group(4))
                return hours * 3600 + minutes * 60 + seconds + centisec / 100
            return None

        except subprocess.TimeoutExpired:
            logger.warning(f"動画情報取得がタイムアウト: {video_path}")
            return None
        except FileNotFoundError:
            logger.error("ffmpeg/ffprobeが見つかりません")
            return None
        except OSError as e:
            logger.error(f"動画情報取得中にOSエラー: {video_path}: {e}")
            return None
