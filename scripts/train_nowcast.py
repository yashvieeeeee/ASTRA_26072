import argparse
import xarray as xr
import torch
from astra_pipeline.model import AstraNowcastNet
from astra_pipeline.training import FusedWindowDataset, TrainingConfig, train_model, evaluate_model

parser=argparse.ArgumentParser(description="Train ASTRA's ConvLSTM multi-head nowcaster on Phase 1 fused data")
parser.add_argument("--train-zarr",required=True); parser.add_argument("--test-zarr",required=True); parser.add_argument("--epochs",type=int,default=5)
parser.add_argument("--checkpoint",default="astra_nowcast.pt")
args=parser.parse_args(); config=TrainingConfig(epochs=args.epochs)
train=xr.open_zarr(args.train_zarr,chunks="auto"); test=xr.open_zarr(args.test_zarr,chunks="auto")
train_windows=FusedWindowDataset(train,config,training_only=True); test_windows=FusedWindowDataset(test,config,training_only=False)
model=AstraNowcastNet(train.atmospheric_state.sizes["feature"])
print("loss by epoch:",train_model(model,train_windows,config)); scores,reliability,tracking=evaluate_model(model,test_windows)
torch.save({"state_dict":model.state_dict(),"features":train.feature.values.tolist()},args.checkpoint)
print(scores); print(reliability); print(tracking)
