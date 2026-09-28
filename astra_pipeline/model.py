"""ConvLSTM multi-head nowcasting network and imbalance-aware objective."""
from __future__ import annotations
import torch
from torch import nn
import torch.nn.functional as F

class ConvLSTMCell(nn.Module):
    def __init__(self, input_channels: int, hidden_channels: int, kernel_size: int = 3):
        super().__init__(); pad=kernel_size//2
        self.hidden_channels=hidden_channels
        self.gates=nn.Conv2d(input_channels+hidden_channels, 4*hidden_channels, kernel_size, padding=pad)
    def forward(self, x, state):
        h,c=state
        i,f,o,g=torch.chunk(self.gates(torch.cat((x,h),dim=1)),4,dim=1)
        c=torch.sigmoid(f)*c+torch.sigmoid(i)*torch.tanh(g)
        return torch.sigmoid(o)*torch.tanh(c),c
    def initial(self,x):
        shape=(x.shape[0],self.hidden_channels,*x.shape[-2:])
        return x.new_zeros(shape),x.new_zeros(shape)

class AstraNowcastNet(nn.Module):
    """Shared temporal encoder with six-lead storm and lightning probability heads."""
    def __init__(self, input_features: int, hidden_channels: int = 32, leads: int = 6, dropout: float = .15):
        super().__init__()
        self.stem=nn.Sequential(nn.Conv2d(input_features,hidden_channels,3,padding=1),nn.GroupNorm(4,hidden_channels),nn.GELU())
        self.encoder=ConvLSTMCell(hidden_channels,hidden_channels)
        self.dropout=nn.Dropout2d(dropout)
        self.storm_head=nn.Conv2d(hidden_channels,leads,1)
        self.lightning_head=nn.Conv2d(hidden_channels,leads,1)
    def forward(self,x):
        """x: [batch, last-hour frames, features, latitude, longitude]."""
        state=None
        for t in range(x.shape[1]):
            encoded=self.stem(x[:,t])
            state=self.encoder(encoded, self.encoder.initial(encoded) if state is None else state)
        latent=self.dropout(state[0])
        return {"storm_logits":self.storm_head(latent),"lightning_logits":self.lightning_head(latent)}

def focal_bce_with_logits(logits, targets, alpha: float=.75, gamma: float=2.0):
    bce=F.binary_cross_entropy_with_logits(logits,targets,reduction="none")
    probability=torch.sigmoid(logits); p_t=probability*targets+(1-probability)*(1-targets)
    alpha_t=alpha*targets+(1-alpha)*(1-targets)
    return (alpha_t*(1-p_t).pow(gamma)*bce).mean()

def multitask_focal_loss(prediction, storm_targets, lightning_targets, lightning_weight: float=1.0):
    return focal_bce_with_logits(prediction["storm_logits"],storm_targets)+lightning_weight*focal_bce_with_logits(prediction["lightning_logits"],lightning_targets)

@torch.no_grad()
def mc_dropout_predict(model, inputs, passes: int=12):
    """Mean probability plus ensemble-agreement confidence for every cell and lead."""
    was_training=model.training; model.train() # activate only dropout; no gradients
    members=[]
    for _ in range(passes):
        output=model(inputs)
        members.append(torch.stack([torch.sigmoid(output["storm_logits"]),torch.sigmoid(output["lightning_logits"])],dim=1))
    samples=torch.stack(members)
    mean=samples.mean(0); confidence=(1-(samples.std(0,unbiased=False)/.5)).clamp(0,1)
    model.train(was_training)
    return {"probability":mean,"confidence":confidence}
