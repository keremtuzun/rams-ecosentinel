import numpy as np
import pytest
import torch

from ecosentinel.metrics import binary_metrics
from ecosentinel.models import FireFusion, SiameseUNet
from ecosentinel.training import network_input, set_seed, tiled_scores


def test_gradient_update_checkpoint_and_inference(tmp_path):
    # Explicitly synthetic unit-test tensors; not scientific training data or claimed model evidence.
    set_seed(42)
    model = SiameseUNet()
    before, after = torch.rand(2, 6, 16, 16), torch.rand(2, 6, 16, 16)
    initial = model.head.weight.clone().detach()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(model(before, after), torch.ones(2, 16, 16))
    loss.backward()
    optimizer.step()
    assert not torch.equal(initial, model.head.weight)
    assert model(before, after).shape == (2, 16, 16)
    torch.save(model.state_dict(), tmp_path / "checkpoint.pt")
    restored = SiameseUNet()
    restored.load_state_dict(torch.load(tmp_path / "checkpoint.pt", weights_only=True))
    model.eval()
    restored.eval()
    torch.testing.assert_close(model(before, after), restored(before, after))


def test_irregular_output_dimensions_and_masking():
    set_seed(1)
    before = np.ones((6, 75, 81), np.float32) * 0.15
    valid = np.ones((75, 81), bool)
    valid[0, 0] = False
    prepared = network_input(before, valid)
    assert (prepared[:, 0, 0] == 0).all()
    assert prepared[0, 1, 1] == 0.5
    result = tiled_scores(SiameseUNet(), before, before, valid)
    assert result.shape == (75, 81)
    assert np.isfinite(result).all() and ((result >= 0) & (result <= 1)).all()


def test_metrics_known_confusion():
    m = binary_metrics([0, 0, 1, 1], [0.1, 0.8, 0.4, 0.9])
    assert m["confusion_matrix"] == [[1, 1], [1, 1]]
    assert m["f1"] == 0.5
    assert m["iou"] == pytest.approx(1 / 3)
    assert m["brier_score"] == pytest.approx(0.255)
    with pytest.raises(ValueError):
        binary_metrics([0, 1], [0.2, float("nan")])


def test_fire_fusion_shape_and_training():
    set_seed(3)
    model = FireFusion()
    image, weather = torch.rand(4, 6, 32, 32), torch.rand(4, 6)
    logits = model(image, weather)
    assert logits.shape == (4,)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, torch.tensor([0.0, 1.0, 0.0, 1.0]))
    loss.backward()
    assert model.head[-1].weight.grad.abs().sum() > 0


def test_missing_model_is_fail_closed(tmp_path):
    from ecosentinel.inference import load_model
    from ecosentinel.common import DataUnavailable

    with pytest.raises(DataUnavailable, match="No evaluated"):
        load_model(tmp_path)
