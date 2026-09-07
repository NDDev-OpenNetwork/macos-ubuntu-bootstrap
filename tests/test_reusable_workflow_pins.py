import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "workflow_pins", ROOT / "scripts/ci/check_reusable_workflow_pins.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def fixture(line: str) -> pathlib.Path:
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / "config").mkdir()
    (directory / ".github/workflows").mkdir(parents=True)
    (directory / "config/reusable-workflow-pins.json").write_text(
        json.dumps({
            "schema_version": 1,
            "repositories": [{
                "repository": "example-org/workflows",
                "version": "1.2.3",
                "commit": "a" * 40,
            }],
        }),
        encoding="utf-8",
    )
    (directory / ".github/workflows/ci.yml").write_text(line, encoding="utf-8")
    return directory


def test_exact_registered_release_pin_passes() -> None:
    root = fixture(
        "uses: example-org/workflows/.github/workflows/ci.yml@" + "a" * 40 + " # 1.2.3\n"
    )
    assert module.validate(root) == []


def test_false_release_comment_is_rejected() -> None:
    root = fixture(
        "uses: example-org/workflows/.github/workflows/ci.yml@" + "a" * 40 + " # 9.9.9\n"
    )
    assert any("want" in problem for problem in module.validate(root))


def test_untagged_or_unregistered_pin_is_rejected() -> None:
    root = fixture(
        "uses: other-org/workflows/.github/workflows/ci.yml@" + "b" * 40 + " # 1.0.0\n"
    )
    problems = module.validate(root)
    assert any("not registered" in problem for problem in problems)
    assert any("unused" in problem for problem in problems)


def test_exact_development_commit_passes_without_a_release_claim() -> None:
    version = "commit:" + "a" * 40
    root = fixture(
        "uses: example-org/workflows/.github/workflows/ci.yml@" + "a" * 40 + " # " + version + "\n"
    )
    path = root / "config/reusable-workflow-pins.json"
    value = json.loads(path.read_text())
    value["repositories"][0]["version"] = version
    path.write_text(json.dumps(value))
    assert module.validate(root) == []


def test_development_identity_must_equal_registered_commit() -> None:
    version = "commit:" + "b" * 40
    root = fixture(
        "uses: example-org/workflows/.github/workflows/ci.yml@" + "a" * 40 + " # " + version + "\n"
    )
    path = root / "config/reusable-workflow-pins.json"
    value = json.loads(path.read_text())
    value["repositories"][0]["version"] = version
    path.write_text(json.dumps(value))
    assert any("invalid release" in problem for problem in module.validate(root))
