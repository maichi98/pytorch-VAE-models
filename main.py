from __future__ import print_function, division
import os
import sys
import argparse
import numpy as np
import torch
import torch.utils.data
from torch import nn, optim
from torch.nn import functional as F
from torchvision import datasets, transforms
from torchvision.utils import save_image
from tensorboardX import SummaryWriter
# import matplotlib.pyplot as plt

from cli import parser
from loss_plot import LossPlot

#
# Parse args
#
args = parser.parse_args()
torch.manual_seed(args.seed)
args.cuda = not args.no_cuda and torch.cuda.is_available()
print(f'Running on GPU: {args.cuda}')
print('Arguments:')
for arg, val in args._get_kwargs():
    print(f'    {arg:14s} {val}')

#
# Create directory where to save the results
#
dirName = f'results_{args.data}_{args.model_name}_zdim-{args.z_dim}_beta-{args.beta}'
if not os.path.exists(dirName):
    os.mkdir(dirName)
    print(f'Directory {dirName} created \n')
else:
    print(f'Directory {dirName} already exists \n')

#
# Load data
#
if args.data.lower() == 'mnist':
    from mnist import load_mnist, models
    img_size = 28
    VAE_model = models[args.model_name]
    train_loader, test_loader = load_mnist(batch_size=args.batch_size)

elif args.data.lower() == 'dsprites':
    from dsprites import load_dsprites, models
    img_size = 64
    VAE_model = models[args.model_name]
    train_loader, test_loader = load_dsprites(dir='/home/genyrosk/datasets',
                                    val_split=0.1, seed=args.seed,
                                    batch_size=args.batch_size)
else:
    raise Exception('Dataset not found. Try: MNIST, dSprites')

print('Total training datapoints:', len(train_loader.sampler))
print('Total testing datapoints:', len(test_loader.sampler))

#
# model + optimizer + learning rate
#
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = VAE_model(z_dim=args.z_dim, img_size=img_size).to(device)
optimizer = optim.Adam(model.parameters(), lr=1e-3)
# scheduler = optim.lr_scheduler.StepLR(optimizer, 1, gamma=0.3)
# scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer,
#                             mode='min', factor=0.1, patience=2,
#                             verbose=True)
scheduler = optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.98)
loss_function = VAE_model.loss_function

print(f'Total parameters: {model.total_parameters}\n')

# plots
if args.tensorboard:
    writer = SummaryWriter()
else:
    loss_plot = LossPlot(epochs=args.epochs,
                         data_len=len(train_loader.sampler),
                         batch_size=args.batch_size,
                         plot_interval=50,
                         dir=dirName)


# train_losses = []
# test_losses = []
# fig, ax = plt.subplots(1,1,figsize=(12,8))

def train(epoch):
    model.train()
    running_loss = 0
    for batch_idx, (data, _) in enumerate(train_loader):
        data = data.to(device)
        # forward pass
        optimizer.zero_grad()
        recon_batch, mu, logvar = model(data)
        # loss + grads backprop
        loss = loss_function(recon_batch, data, mu, logvar, beta=args.beta)
        loss.backward()
        # save
        running_loss += loss.item()
        # train_losses.append(loss.item())
        # update weights
        optimizer.step()
        # plot
        if args.tensorboard:
            writer.add_scalars('train_data',
                               {'loss': loss.item()/args.batch_size},
                               batch_idx*epoch)
        else:
            loss_plot.add_item(loss.item()/args.batch_size)

        if batch_idx % args.log_interval == 0 and batch_idx != 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader),
                loss.item() / len(data)))

    # update learning rate
    scheduler.step()
    # print
    avg_loss = running_loss / len(train_loader.sampler)
    print(f'====> Epoch: {epoch} Average loss: {avg_loss:.4f}')


def test(epoch):
    model.eval()
    test_loss = 0
    with torch.no_grad():
        for i, (data, _) in enumerate(test_loader):
            data = data.to(device)
            recon_batch, mu, logvar = model(data)
            loss = loss_function(recon_batch, data, mu, logvar, beta=args.beta)
            test_loss += loss.item()
            # test_losses.append(loss.item())
            if i == 0:
                n = min(data.size(0), 8)
                recon_batch = recon_batch.view(args.batch_size, 1, img_size, img_size)
                comparison = torch.cat([data[:n], recon_batch[:n]])
                save_image(comparison.cpu(),
                         f'{dirName}/reconstruction_{str(epoch)}.png', nrow=n)

    test_loss /= len(test_loader.sampler)
    # plot
    if args.tensorboard:
        writer.add_scalars('test_data',
                           {'loss': test_loss},
                           epoch*len(train_loader))
    else:
        loss_plot.add_test_item(test_loss)

    print(f'====> Test set loss: {test_loss:.4f}')


for epoch in range(1, args.epochs + 1):
    train(epoch)
    test(epoch)

    for param_group in optimizer.param_groups:
        print(f'====> Learning rate: {param_group["lr"]:.7f}')

    # samples
    with torch.no_grad():
        sample = torch.randn(64, args.z_dim).to(device)
        sample = model.decode(sample).cpu()
        save_image(sample.view(64, 1, img_size, img_size),
                   f'{dirName}/sample_{str(epoch)}.png')

#
# save model
#
checkpoint = {'model': model,
              'state_dict': model.state_dict(),
              'optimizer' : optimizer.state_dict()}
model_out_path = f"{dirName}/{args.model_name}_model.pth"
torch.save(checkpoint, model_out_path)
print(f"Model saved to {model_out_path}")

#
# Sample latent space
#
nums = 11
x_range = np.linspace(-3,3,nums)
z = np.zeros((args.z_dim, nums, args.z_dim), dtype=np.float32)
for dim in range(args.z_dim):
    z[dim, :, dim] = x_range

z = torch.tensor(z).view(args.z_dim*nums, z.shape[-1]).to(device)
sample = model.decode(z).cpu()
save_image(sample.view(args.z_dim*nums, 1, img_size, img_size),
           f'{dirName}/sample_latent_space.png',
           nrow=nums)
print(f"Latent space sampled")
