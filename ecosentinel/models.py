import torch
from torch import nn
from torch.nn import functional as F


def block(inputs, outputs):
    return nn.Sequential(
        nn.Conv2d(inputs, outputs, 3, padding=1),
        nn.GroupNorm(4, outputs),
        nn.SiLU(),
        nn.Conv2d(outputs, outputs, 3, padding=1),
        nn.GroupNorm(4, outputs),
        nn.SiLU(),
    )


class SiameseUNet(nn.Module):
    """Shared temporal encoder, ordered features and differences; initialized from scratch."""

    def __init__(self, bands=6, width=12):
        super().__init__()
        self.encoder1 = block(bands, width)
        self.encoder2 = block(width, width * 2)
        self.fusion = block(width * 6, width * 2)
        self.decoder = block(width * 5, width)
        self.head = nn.Conv2d(width, 1, 1)

    def forward(self, before, after):
        a, b = self.encoder1(before), self.encoder1(after)
        aa, bb = self.encoder2(F.avg_pool2d(a, 2)), self.encoder2(F.avg_pool2d(b, 2))
        fused = self.fusion(torch.cat([aa, bb, bb - aa], dim=1))
        up = F.interpolate(fused, size=a.shape[-2:], mode="bilinear", align_corners=False)
        decoded = self.decoder(torch.cat([up, a, b, b - a], dim=1))
        return self.head(decoded).squeeze(1)


class FireFusion(nn.Module):
    """Seven-day future thermal-observation target; requires as-of features and grouped splits."""

    def __init__(self, weather_features=6, width=12):
        super().__init__()
        self.image = nn.Sequential(
            block(6, width), nn.AvgPool2d(2), block(width, width * 2), nn.AdaptiveAvgPool2d(1), nn.Flatten()
        )
        self.weather = nn.Sequential(nn.Linear(weather_features, 16), nn.SiLU(), nn.Dropout(0.15))
        self.head = nn.Sequential(nn.Linear(width * 2 + 16, 16), nn.SiLU(), nn.Linear(16, 1))

    def forward(self, image, weather):
        return self.head(torch.cat([self.image(image), self.weather(weather)], 1)).squeeze(1)
