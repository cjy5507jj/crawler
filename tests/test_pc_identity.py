from src.normalization.pc_identity import build_pc_identity


def test_build_pc_identity_uses_dynamic_normalized_tokens() -> None:
    identity = build_pc_identity("gpu", "MSI 지포스 RTX 5070 게이밍 트리오 OC D7 12GB")

    assert identity.domain == "pc_parts"
    assert identity.canonical_key == "pc_parts:gpu:msi:rtx5070:gaming-trio"
    assert identity.specs["brand"] == "msi"
    assert identity.specs["category_tokens"] == ["rtx5070"]


def test_build_pc_identity_includes_capacity_for_storage() -> None:
    identity = build_pc_identity("ssd", "삼성전자 990 PRO M.2 NVMe 2TB")

    assert identity.canonical_key == "pc_parts:ssd:samsung:990pro:m.2-nvme:2tb"
    assert identity.specs["capacity_tokens"] == ["2tb"]
