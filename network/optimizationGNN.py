from network.encoderCNN import *
import sys
import torch.nn as nn
import os
import numpy as np
from torch_geometric.nn import MetaLayer
from torch_geometric.nn import GCNConv
from torch_geometric.nn import SGConv
import torch.nn.functional as F
import torch


class optimNet(nn.Module):
    def __init__(self):
        super(optimNet, self).__init__()
        self.conv1 = GCNConv(512, 512, improved=False, cached=False, bias=True)
        #self.conv1 = SGConv(512, 512, K = 5, cached=False, bias=True)
        self.conv2 = GCNConv(512, 128, improved=False, cached=False, bias=True)
        #self.conv2 = SGConv(512, 128, K = 5, cached=False, bias=True)
        self.mlp1 = nn.Sequential(
            nn.Linear(1024 , 1), #loads features from two nodes and features of their edge (edge of interest)
            nn.ReLU()
        )
    def similarity1(self, node_embedding, edge_index):
        edge_attr = []
        for i in range(len(edge_index[0])):
            #print("input mlp1:" + str(torch.cat((node_embedding[edge_index[0][i]], node_embedding[edge_index[1][i]]), 0).shape))
            x1 = self.mlp1(torch.cat((node_embedding[edge_index[0][i]], node_embedding[edge_index[1][i]]), 0))
            #print("output mlp1")
            edge_attr.append(x1.reshape(1))
        edge_attr = torch.stack(edge_attr)
        return edge_attr
    def forward(self, node_attr, edge_attr, edge_index, coords, frame):
        node_embedding= node_attr
        out = self.conv1(node_embedding, edge_index, edge_attr.reshape(-1))
        out = F.relu(out)
        edge_attr = self.similarity1(out, edge_index)
        out = self.conv2(out, edge_index, edge_attr.reshape(-1))
        return out

    def configure_input_size(self, shape):
        self.conv1 = GCNConv(shape, 512, improved=False, cached=False, bias=True)
        #self.conv1 = SGConv(shape, 512, K = 5 , cached=False, bias=True)
        #self.mlp1 = nn.Sequential(
            #nn.Linear(shape*2, 1),  # loads features from two nodes and features of their edge (edge of interest)
            #nn.ReLU()
        #)
