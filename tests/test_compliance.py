"""Static compliance checks for release metadata and attribution documents."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_installer_points_to_project_repository() -> None:
    text = (PROJECT_ROOT / "installer.iss").read_text(encoding="utf-8-sig")
    assert '#define MyAppURL "https://github.com/Cat-Drink/VideoGetTool"' in text
    assert "Evil0ctal/Douyin_TikTok_Download_API" not in text


def test_upstream_notice_defines_license_boundary() -> None:
    text = (PROJECT_ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    assert "Evil0ctal/Douyin_TikTok_Download_API" in text
    assert "Apache-2.0" in text
    assert "未直接复制" in text
    # v0.3.0 起：项目协议由 MIT 切换为 Apache License 2.0
    assert "Apache License 2.0" in text


def test_signer_vector_provenance_is_documented() -> None:
    text = (PROJECT_ROOT / "tests" / "data" / "README.md").read_text(encoding="utf-8")
    assert "known_signer_vectors.json" in text
    assert "独立生成" in text


def test_code_origin_audit_covers_high_risk_files() -> None:
    text = (PROJECT_ROOT / "docs" / "compliance" / "v0.3.0-code-origin-audit.md").read_text(
        encoding="utf-8"
    )
    for path in (
        "crawlers/signer/xbogus.py",
        "crawlers/signer/abogus.py",
        "crawlers/video_parser.py",
        "crawlers/user_home_crawler.py",
        "crawlers/api_spec.py",
    ):
        assert path in text
    assert "残余风险" in text
    assert "不构成法律意见" in text


def test_readme_links_third_party_notice() -> None:
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "THIRD-PARTY-NOTICES.md" in text


def test_architecture_doc_does_not_claim_scraped_vectors() -> None:
    text = (PROJECT_ROOT / "docs" / "structure" / "03-系统架构设计文档.md").read_text(
        encoding="utf-8"
    )
    assert "从开源项目抓取参考" not in text
    assert "独立生成" in text
