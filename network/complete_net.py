import sys
import torch.nn as nn
import os
import numpy as np
from network.optimizationGNN import *
from network.encoderCNN import *
from network.detections import *
from network.affinity import *
from network.affinity_appearance import *
from network.affinity_geom import *
from torch.nn.parameter import Parameter
from utils import *
import torch
from torch_sparse import transpose
from network.affinity_final import *

class completeNet(nn.Module):
    def __init__(self):
        super(completeNet, self).__init__()

        self.cnn = EncoderCNN()
        self.affinity_net = affinityNet()
        self.affinity_appearance_net= affinity_appearanceNet()
        self.affinity_geom_net= affinity_geomNet()
        self.affinity_final_net= affinity_finalNet()
        self.optim_net = optimNet()
        self.cos = nn.CosineSimilarity(dim=0, eps=1e-6)

    def forward(self, data):
        # print('Inside Model:  num graphs: {}, device: {}'.format(data.num_graphs, data.batch.device))
        # device = torch.device('cuda')
        x, coords_original, edge_index, ground_truth, coords, edges_number_list, frame, track_num, detections_num= \
            data.x, data.coords_original, data.edge_index, data.ground_truth, data.coords, data.edges_number, data.frame, data.track_num, data.det_num
        slack= torch.Tensor([0.2]).float().cuda()
        lam= torch.Tensor([5]).float().cuda()
        #Pass through GNN
        #print("Shape of x: " + str(x.shape))
        node_embedding = self.cnn(x)
        #print("Shape of node embedding: " + str(node_embedding.shape))
        edge_embedding = []
        edge_mlp= []
        edge_mlp2 = []
        self.affinity_appearance_net.configure_input_size(shape = list(node_embedding.shape)[1] * 2)
        #print(list(node_embedding.shape)[1] * 2)
        self.affinity_appearance_net = self.affinity_appearance_net.to("cuda")
        for i in range(len(edge_index[0])):
            #CNN features
            #print("Shape of affinity app input: " + str(torch.cat((node_embedding[edge_index[0][i]], node_embedding[edge_index[1][i]]), 0).shape))
            #self.affinity_appearance_net.configure_input_size(list(torch.cat((node_embedding[edge_index[0][i]], node_embedding[edge_index[1][i]]), 0).shape)[0])
            #self.affinity_appearance_net.configure_input_size(list(node_embedding.shape)[0]*2)
            #self.affinity_appearance_net = self.affinity_appearance_net.to("cuda")
            x1 = self.affinity_appearance_net(torch.cat((node_embedding[edge_index[0][i]], node_embedding[edge_index[1][i]]), 0))
            #print("Shape of affinity app output: " + str(x1.shape))
            #geometry
            #print("Input of af geo: " + str(torch.cat((coords[edge_index[0][i]], coords[edge_index[1][i]]), 0).shape))
            x2 = self.affinity_geom_net(torch.cat((coords[edge_index[0][i]], coords[edge_index[1][i]]), 0))
            #print("Output of affinity geo: " + str(x2.shape))
            #iou
            iou= box_iou_calc(coords_original[edge_index[0][i]], coords_original[edge_index[1][i]])
            #print("Shape of iou  output: " + str(iou.shape))
            # x2= iou
            edge_mlp.append(iou)
            #pass through mlp
            #print(inputs.shape)
            inputs = torch.cat((x1.reshape(1), x2.reshape(1)), 0)
            #print("Inputs shape: " + str(inputs.shape))
            edge_embedding.append(self.affinity_net(inputs))
        edge_embedding= torch.stack(edge_embedding)
        #print("Shape of optim input node: " + str(node_embedding.shape))
        #print("Shape of optim input edge: " + str(edge_embedding.shape))
        #print("Optim net input edgeindex:" + str(edge_index.shape))
        #print("Optim net input coords:" + str(coords.shape))
        #print("Optim net input frame:" + str(frame.shape))
        #print("Optim net input node shape1:" + str(list(node_embedding.shape)[1]))
        self.optim_net.configure_input_size(list(node_embedding.shape)[1])
        self.optim_net = self.optim_net.to("cuda")
        output = self.optim_net(node_embedding, edge_embedding, edge_index, coords, frame)
        #print("Shape of optim output: " + str(output.shape))
        output_temp= []
        for i in range(len(edge_index[0])):
            if edge_index[0][i]<edge_index[1][i]:
                nodes_difference= self.cos(output[edge_index[0][i]], output[edge_index[1][i]])
                #print("Shape of affinity final input: " + str(torch.cat((nodes_difference.reshape(1), edge_mlp[i].reshape(1)), 0).shape))
                x1 = self.affinity_final_net(torch.cat((nodes_difference.reshape(1), edge_mlp[i].reshape(1)), 0))
                #print("Shape of affinity final output: " + str(x1.shape))
                output_temp.append(x1.reshape(1))
        output= output_temp
        start1= 0
        start2 = 0 #two are used here because output is already reduced while edges not
        normalized_output= []
        cosines_list = []
        tracklet_num = []
        det_num = []
        for i,j in enumerate(data.idx):
            num_of_edges1= edges_number_list[i].item()
            num_of_edges2= int(num_of_edges1/2)
            output_sliced= output[start2:start2+num_of_edges2]
            edges_sliced= edge_index[:, start1:start1+num_of_edges1]
            start1 += num_of_edges1
            start2 += num_of_edges2
            row, col = edges_sliced
            mask = row < col
            edges_sliced = edges_sliced[:, mask]
            num_of_nodes= sum(track_num[0:i])+sum(detections_num[0:i])
            for k,l  in enumerate(edges_sliced):
                for m,n in enumerate(l): 
                    edges_sliced[k,m]= edges_sliced[k,m]-num_of_nodes
            # elevate to e power and augment with slack variable
            matrix = []
            for k in range(int(track_num[i].item())):
                matrix.append([])
                for l in range(int(detections_num[i].item())):
                    matrix[k].append(torch.zeros(1, dtype=torch.float, requires_grad=False).cuda())
                matrix[k].append(torch.exp(slack*lam))#slack
            for k,m in enumerate(edges_sliced[0]):
                matrix[int(edges_sliced[0,k].item())][int(edges_sliced[1,k].item())-int(track_num[i].item())]= torch.exp(output_sliced[k]*lam)
            for w,z in enumerate(matrix):
                matrix[w] = torch.cat(z)
            matrix.append(torch.ones(len(matrix[0])).cuda()*torch.exp(slack*lam))#slack
            matrix = torch.stack(matrix)
            matrix = sinkhorn(matrix)
            matrix = matrix[0:-1,0:-1]
            det_num.append(torch.tensor(len(matrix[0]), dtype= int).cuda())
            tracklet_num.append(torch.tensor(len(matrix), dtype= int).cuda())
            normalized_output.append(matrix.reshape(-1))
        normalized_output = torch.cat((normalized_output[:]),dim=0)
        normalized_output_final= []
        ground_truth_final= []
        for k, l in enumerate(normalized_output):
            if l.item()!=0:
                normalized_output_final.append(l)
                ground_truth_final.append(ground_truth[k])
        return torch.stack(normalized_output_final), normalized_output, torch.stack(ground_truth_final), ground_truth, torch.stack(det_num), torch.stack(tracklet_num)