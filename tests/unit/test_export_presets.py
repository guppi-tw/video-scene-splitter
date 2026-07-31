from app.core.export_presets import get_export_preset


def test_export_presets_keep_fast_copy_default_and_offer_exact_boundaries():
    share = get_export_preset("share_fast")
    archive = get_export_preset("archive_fast")
    exact = get_export_preset("exact")

    assert (share.auto_split, share.use_copy) == (True, True)
    assert (archive.auto_split, archive.use_copy) == (False, True)
    assert (exact.auto_split, exact.use_copy) == (True, False)
    assert exact.label == "境界を正確に"
