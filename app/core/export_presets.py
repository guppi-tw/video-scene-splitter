"""用途から書き出し方式を選べる、小さなプリセット定義。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportPreset:
    id: str
    label: str
    description: str
    auto_split: bool
    use_copy: bool


EXPORT_PRESETS = (
    ExportPreset(
        id="share_fast",
        label="みてね（高速）",
        description="9分55秒以内に分割し、元画質のまま高速に書き出します",
        auto_split=True,
        use_copy=True,
    ),
    ExportPreset(
        id="archive_fast",
        label="元画質で保管",
        description="長さを変えず、元画質のまま高速に書き出します",
        auto_split=False,
        use_copy=True,
    ),
    ExportPreset(
        id="exact",
        label="境界を正確に",
        description="9分55秒以内に分割し、正確な境界で再エンコードします",
        auto_split=True,
        use_copy=False,
    ),
)

_BY_ID = {preset.id: preset for preset in EXPORT_PRESETS}


def get_export_preset(preset_id: str) -> ExportPreset:
    """不明な保存値は安全な既定プリセットへフォールバックする。"""
    return _BY_ID.get(preset_id, _BY_ID["share_fast"])
