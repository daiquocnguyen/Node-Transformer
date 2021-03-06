#! /usr/bin/env python

import tensorflow as tf
import numpy as np
import os
import time
import datetime
from model_SANNE_squash import SANNE
import pickle as cPickle
from utils import *
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
np.random.seed(1234)
tf.set_random_seed(1234)

# Parameters
# ==================================================

parser = ArgumentParser("SANNE", formatter_class=ArgumentDefaultsHelpFormatter, conflict_handler='resolve')

parser.add_argument("--data", default="../graph/", help="Data sources.")
parser.add_argument("--run_folder", default="../", help="")
parser.add_argument("--name", default="cora.128.8.ind1.pickle", help="Name of the dataset.")
parser.add_argument("--embedding_dim", default=4, type=int, help="Dimensionality of character embedding")
parser.add_argument("--learning_rate", default=0.0001, type=float, help="Learning rate")
parser.add_argument("--batch_size", default=8, type=int, help="Batch Size")
parser.add_argument("--idx_time", default=1, type=int, help="")
parser.add_argument("--num_epochs", default=50, type=int, help="Number of training epochs")
parser.add_argument("--saveStep", default=1, type=int, help="")
parser.add_argument("--allow_soft_placement", default=True, type=bool, help="Allow device soft device placement")
parser.add_argument("--log_device_placement", default=False, type=bool, help="Log placement of ops on devices")
parser.add_argument("--model_name", default='cora_inds', help="")
parser.add_argument("--useInductive", action='store_true')
parser.add_argument('--num_sampled', default=32, type=int, help='')
parser.add_argument("--is_trainable", default=False, type=bool, help="")
parser.add_argument("--write_file", default='cora', help="")
parser.add_argument("--dropout_keep_prob", default=1.0, type=float, help="Dropout keep probability")
parser.add_argument("--num_hidden_layers", default=4, type=int, help="Number of attention layers")
parser.add_argument("--num_heads", default=4, type=int, help="Number of attention heads within each attention layer")
parser.add_argument("--ff_hidden_size", default=1024, type=int, help="The hidden size for the feedforward layer")
parser.add_argument("--num_neighbors", default=4, type=int, help="")
parser.add_argument("--nameTrans", default="cora.128.8.trans.pickle", help="Name of the dataset.")
parser.add_argument("--idx_time", default=1, type=int, help="")
parser.add_argument("--numIndRW", default=8, type=int, help="")
parser.add_argument("--use_pos", default=1, type=int, help="0 when not using positional embeddings. Otherwise.")
args = parser.parse_args()

print(args)


class Batch_Loader_RW(object):
    def __init__(self, walks):
        self.walks = walks
        self.data_size = len(self.walks)
        self.sequence_length = np.shape(self.walks)[1]
        self.check()
        self.getNeighbors()
    def __call__(self):
        idxs = np.random.randint(0, self.data_size, args.batch_size)
        arrY = []
        for walk in self.walks[idxs]:
            for tmpNode in walk:
                arrY.append(np.random.choice(self.node_neighbors[tmpNode], args.num_neighbors, replace=True))
        return self.walks[idxs], np.reshape(np.array(arrY), (args.num_neighbors*self.sequence_length*args.batch_size, -1))

    def check(self):
        _dict = set()
        for walk in self.walks:
            for tmp in walk:
                if tmp not in _dict:
                    _dict.add(int(tmp))
        self._dict = _dict

    def getNeighbors(self):
        self.node_neighbors = {}

        with open('../data/' + str(args.name).split('.')[0] + '.ind.edgelist'
               + str(args.name).split('.')[-2][-1], 'r') as f:
            for line in f:
                tmpNodes = line.strip().split()
                if len(tmpNodes) == 2:
                    if int(tmpNodes[0]) not in self.node_neighbors:
                        self.node_neighbors[int(tmpNodes[0])] = []
                    self.node_neighbors[int(tmpNodes[0])].append(int(tmpNodes[1]))

# Load data
print("Loading data...")

with open(args.data + args.name, 'rb') as f:
    walks = cPickle.load(f)
batch_rw = Batch_Loader_RW(walks)

#cora,citeseer,pubmed
with open('../data/' + str(args.name).split('.')[0] + '.128d.feature.pickle', 'rb') as f:
    features_matrix = cPickle.load(f)
feature_dim_size = features_matrix.shape[1]
vocab_size = features_matrix.shape[0]

#####
with open(args.data + args.nameTrans, 'rb') as f:
    walksTrans = cPickle.load(f) #random walks from the original graph for inferring node embeddings of unseen nodes in the inductive setting

datasplit = open("../data/" + str(args.name).split('.')[0] + '.10sampledtimes', 'rb')
for idx in range(args.idx_time):
    idx_train, train_labels, idx_val, val_labels, idx_test, test_labels = cPickle.load(datasplit)

lstInd = {}
totalIndTestX = []
totalIndTestY = []
for tmpX in walksTrans:
    if tmpX[0] in set(idx_test): #1000
        if tmpX[0] not in lstInd:
           lstInd[tmpX[0]] = 0
        if lstInd[tmpX[0]] == args.numIndRW: #8
            break
        lstInd[tmpX[0]] += 1
        totalIndTestX.append(tmpX)
        for tmpY in tmpX:
            for _ in range(args.num_neighbors):
                totalIndTestY.append([tmpY])

totalIndTestX = np.array(totalIndTestX)
totalIndTestY = np.array(totalIndTestY)

print(totalIndTestX.shape, totalIndTestY.shape)

assert len(totalIndTestX) % args.batch_size == 0

print("Loading data... finished!")

# Training
# ==================================================


with tf.Graph().as_default():
    session_conf = tf.ConfigProto(allow_soft_placement=args.allow_soft_placement, log_device_placement=args.log_device_placement)
    session_conf.gpu_options.allow_growth = True
    sess = tf.Session(config=session_conf)
    with sess.as_default():
        global_step = tf.Variable(0, name="global_step", trainable=False)
        selfG = SANNE(sequence_length=batch_rw.sequence_length,
                          num_hidden_layers=args.num_hidden_layers,
                          vocab_size=vocab_size,
                          batch_size=args.batch_size,
                          num_sampled=args.num_sampled,
                          initialization=features_matrix,
                          feature_dim_size=feature_dim_size,
                          num_heads=args.num_heads,
                          ff_hidden_size=args.ff_hidden_size,
                          num_neighbors=args.num_neighbors,
                          use_pos=args.use_pos
                          )

        # Define Training procedure
        optimizer = tf.train.AdamOptimizer(learning_rate=args.learning_rate)
        grads_and_vars = optimizer.compute_gradients(selfG.total_loss)
        train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step)

        out_dir = os.path.abspath(os.path.join(args.run_folder, "runs_SANNE_ind", args.model_name))
        print("Writing to {}\n".format(out_dir))

        # Checkpoint directory. Tensorflow assumes this directory already exists so we need to create it
        checkpoint_dir = os.path.abspath(os.path.join(out_dir, "checkpoints"))
        checkpoint_prefix = os.path.join(checkpoint_dir, "model")
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)

        # Initialize all variables
        sess.run(tf.global_variables_initializer())
        graph = tf.get_default_graph()


        def getOutputEncoder(x_batch, y_batch):
            feed_dict = {
                selfG.input_x: x_batch,
                selfG.input_y: y_batch,
                selfG.dropout_keep_prob: 1.0
            }
            step, outputEncoderInd = sess.run([global_step, selfG.outputEncoderInd], feed_dict)
            return outputEncoderInd

        def train_step(x_batch, y_batch):
            """
            A single training step
            """
            feed_dict = {
                selfG.input_x: x_batch,
                selfG.input_y: y_batch,
                selfG.dropout_keep_prob: args.dropout_keep_prob
            }
            _, step, loss = sess.run([train_op, global_step, selfG.total_loss], feed_dict)
            return loss

        num_batches_per_epoch = int((batch_rw.data_size - 1) / args.batch_size) + 1
        for epoch in range(1, args.num_epochs+1):
            loss = 0
            for batch_num in range(num_batches_per_epoch):
                x_batch, y_batch = batch_rw()
                loss += train_step(x_batch, y_batch)
                current_step = tf.train.global_step(sess, global_step)
            #print(loss)
            if epoch % args.saveStep == 0:
                # It will give tensor object
                embeddingW = graph.get_tensor_by_name('W:0')
                # To get the value (numpy array)
                embeddingW_value = sess.run(embeddingW)

                # averaging the outputs of the encoder into the node embeddings
                indEmbeddings = []
                tmpIdx = range(0, totalIndTestX.shape[0] + 1, args.batch_size)
                for i in range(len(tmpIdx) - 1):
                    x_input = totalIndTestX[tmpIdx[i]:tmpIdx[i + 1]]
                    y_input = totalIndTestY[(tmpIdx[i]*totalIndTestX.shape[1]*args.num_neighbors):(tmpIdx[i + 1]*totalIndTestX.shape[1]*args.num_neighbors)]
                    indEmbeddings.append(getOutputEncoder(x_input, y_input))

                index_from_walks = range(0, totalIndTestX.shape[0]*totalIndTestX.shape[1], totalIndTestX.shape[1])
                indEmbeddings = np.concatenate(indEmbeddings, axis=0)
                indEmbeddings = indEmbeddings[index_from_walks]

                index_nodes_from_walks = totalIndTestX[:,0]
                assert len(indEmbeddings) == len(index_nodes_from_walks)

                totalEmbeddings = {}
                for i in range(len(index_nodes_from_walks)):
                    if index_nodes_from_walks[i] not in totalEmbeddings:
                        totalEmbeddings[index_nodes_from_walks[i]] = []
                    totalEmbeddings[index_nodes_from_walks[i]].append(indEmbeddings[i])

                for k in totalEmbeddings:
                    tmpValue = np.sum(totalEmbeddings[k], axis=0)
                    totalEmbeddings[k] = tmpValue

                lstIdxes = list(totalEmbeddings.keys())
                tmpIndEmbeddings = list(totalEmbeddings.values())

                embeddingW_value[lstIdxes] = tmpIndEmbeddings

                with open(checkpoint_prefix + '-' + str(epoch), 'wb') as f:
                    cPickle.dump(embeddingW_value, f)
                    # cPickle.dump(embeddings_rw, f)
                print("Save embeddings to {}\n".format(checkpoint_prefix + '-' + str(epoch)))
