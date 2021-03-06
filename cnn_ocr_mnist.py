# pylint: disable=C0111,too-many-arguments,too-many-instance-attributes,too-many-locals,redefined-outer-name,fixme
# pylint: disable=superfluous-parens, no-member, invalid-name
import logging
import random
import sys
from io import BytesIO

import gzip
import struct

import mxnet as mx
import numpy as np
from captcha.image import ImageCaptcha

import cv2

sys.path.insert(0, "../../python")
head = '%(asctime)-15s %(message)s'
logging.basicConfig(level=logging.DEBUG, format=head)


def read_data(label_url, image_url):
    with gzip.open(label_url) as flbl:
        magic, num = struct.unpack(">II", flbl.read(8))
        label = np.fromstring(flbl.read(), dtype=np.int8)
    with gzip.open(image_url, 'rb') as fimg:
        magic, num, rows, cols = struct.unpack(">IIII", fimg.read(16))
        image = np.fromstring(fimg.read(), dtype=np.uint8).reshape(
            len(label), rows, cols)
    return (label, image)


def Get_image_lable(img, lable):
    x = [random.randint(0, 9) for x in range(3)]
    black = np.zeros((28, 28), dtype='uint8')
    for i in range(3):
        if x[i] == 0:
            img[:, i * 28:(i + 1) * 28] = black
            lable[i] = 10
    return img, lable


class OCRBatch(object):
    def __init__(self, data_names, data, label_names, label):
        self.data = data
        self.label = label
        self.data_names = data_names
        self.label_names = label_names

    @property
    def provide_data(self):
        return [(n, x.shape) for n, x in zip(self.data_names, self.data)]

    @property
    def provide_label(self):
        return [(n, x.shape) for n, x in zip(self.label_names, self.label)]


class OCRIter(mx.io.DataIter):
    def __init__(self, count, batch_size, num_label, height, width, lable, image):
        super(OCRIter, self).__init__()

        self.batch_size = batch_size
        self.count = count
        self.height = height
        self.width = width
        self.provide_data = [('data', (batch_size, 1, height, width))]
        self.provide_label = [('softmax_label', (self.batch_size, num_label))]
        self.lable = lable
        self.image = image
        self.num_label = num_label

    def __iter__(self):
        for k in range(self.count / self.batch_size):
            data = []
            label = []
            for i in range(self.batch_size):
                num = [random.randint(0, self.count - 1)
                       for i in range(self.num_label)]
                img, lab = Get_image_lable(np.hstack(
                    (self.image[x] for x in num)), np.array([self.lable[x] for x in num]))
                img = np.multiply(img, 1 / 255.0)
                data.append(img.reshape(1, self.height, self.width))
                label.append(lab)

            data_all = [mx.nd.array(data)]
            label_all = [mx.nd.array(label)]
            data_names = ['data']
            label_names = ['softmax_label']

            data_batch = OCRBatch(data_names, data_all, label_names, label_all)
            yield data_batch

    def reset(self):
        pass


def get_ocrnet():
    data = mx.symbol.Variable('data')
    label = mx.symbol.Variable('softmax_label')
    conv1 = mx.symbol.Convolution(data=data, kernel=(5, 5), num_filter=32)
    pool1 = mx.symbol.Pooling(
        data=conv1, pool_type="max", kernel=(2, 2), stride=(1, 1))
    relu1 = mx.symbol.Activation(data=pool1, act_type="relu")

    conv2 = mx.symbol.Convolution(data=relu1, kernel=(5, 5), num_filter=32)
    pool2 = mx.symbol.Pooling(
        data=conv2, pool_type="avg", kernel=(2, 2), stride=(1, 1))
    relu2 = mx.symbol.Activation(data=pool2, act_type="relu")

    conv3 = mx.symbol.Convolution(data=relu2, kernel=(3, 3), num_filter=32)
    pool3 = mx.symbol.Pooling(
        data=conv3, pool_type="avg", kernel=(2, 2), stride=(1, 1))
    relu3 = mx.symbol.Activation(data=pool3, act_type="relu")

    conv4 = mx.symbol.Convolution(data=relu3, kernel=(3, 3), num_filter=32)
    pool4 = mx.symbol.Pooling(
        data=conv4, pool_type="avg", kernel=(2, 2), stride=(1, 1))
    relu4 = mx.symbol.Activation(data=pool4, act_type="relu")

    flatten = mx.symbol.Flatten(data=relu4)
    fc1 = mx.symbol.FullyConnected(data=flatten, num_hidden=256)
    fc21 = mx.symbol.FullyConnected(data=fc1, num_hidden=11)
    fc22 = mx.symbol.FullyConnected(data=fc1, num_hidden=11)
    fc23 = mx.symbol.FullyConnected(data=fc1, num_hidden=11)
    fc2 = mx.symbol.Concat(*[fc21, fc22, fc23], dim=0)
    label = mx.symbol.transpose(data=label)
    label = mx.symbol.Reshape(data=label, target_shape=(0, ))
    return mx.symbol.SoftmaxOutput(data=fc2, label=label, name="softmax")


def Accuracy(label, pred):
    label = label.T.reshape((-1, ))
    hit = 0
    total = 0
    for i in range(pred.shape[0] / 3):
        ok = True
        for j in range(3):
            k = i * 3 + j
            if np.argmax(pred[k]) != int(label[k]):
                ok = False
        if ok:
            hit += 1
        total += 1
    return 1.0 * hit / total


if __name__ == '__main__':
    network = get_ocrnet()
    shape = {"data": (8, 1, 28, 84), "softmax_label": (8, 3)}
    g = mx.viz.plot_network(network, shape=shape)
    g.render(filename='net', cleanup=True)

    devs = [mx.cpu(i) for i in range(1)]

    _, arg_params, __ = mx.model.load_checkpoint("cnn-ocr-mnist", 1)

    model = mx.mod.Module(network, context=devs)

    (train_lable, train_image) = read_data(
        'train-labels-idx1-ubyte.gz', 'train-images-idx3-ubyte.gz')
    (test_lable, test_image) = read_data(
        't10k-labels-idx1-ubyte.gz', 't10k-images-idx3-ubyte.gz')

    batch_size = 8
    data_train = OCRIter(60000, batch_size, 3, 28,
                         84, train_lable, train_image)
    data_test = OCRIter(5000, batch_size, 3, 28, 84, test_lable, test_image)

    model.fit(
        data_train,
        eval_data=data_test,
        num_epoch=1,
        optimizer='sgd',
        eval_metric=Accuracy,
        arg_params=arg_params,
        initializer=mx.init.Xavier(factor_type="in", magnitude=2.34),
        optimizer_params={'learning_rate': 0.001, 'wd': 0.00001},
        batch_end_callback=mx.callback.Speedometer(batch_size, 50),
    )
    model.save_checkpoint(prefix="cnn-ocr-mnist", epoch=2)
