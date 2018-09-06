import argparse
import math
import sys
import random
from sklearn.model_selection import KFold
from sklearn.model_selection import train_test_split
from sklearn import svm
import pickle
from sklearn.externals import joblib
import numpy as np
from numpy.random import seed
seed(1)
import h5py
from sklearn.metrics import confusion_matrix, accuracy_score
from keras.layers import Input, Activation, Dense, Dropout
from keras.layers.normalization import BatchNormalization 
from keras.optimizers import Adam
from keras.models import Model, load_model
from keras.layers.advanced_activations import ELU
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt

''' This code is based on Núñez-Marcos, A., Azkune, G., & Arganda-Carreras, 
    I. (2017). "Vision-Based Fall Detection with Convolutional Neural Networks"
    Wireless Communications and Mobile Computing, 2017.
    Also, new features were added by Gabriel Pellegrino Silva working in 
    Semantix. 
'''

''' Documentation: class Train
    
    This class has a few methods:

    pre_train_cross
    pre_train
    cross_train
    train
    evaluate
    plot_training_info

    The methods that should be called outside of this class are:

    cross_train: perform a n_split cross_train on files passed by
    argument

    train: perfom a simple trainment on files passsed by argument
'''
class Train:

    def __init__(self, threshold, epochs, learning_rate, 
    weight_0, mini_batch_size, id, batch_norm):

        '''
            Necessary parameters to train

        '''

        self.features_key = 'features' 
        self.labels_key = 'labels'
        self.samples_key = 'samples'
        self.num_key = 'num'

        self.id = id

        self.threshold = threshold
        self.num_features = 4096
        self.sliding_height = 10
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.weight_0 = weight_0
        self.mini_batch_size = mini_batch_size
        self.batch_norm = batch_norm 

        self.classifier = []

    def cross_train(self, streams, nsplits):

        self.kf_falls = KFold(n_splits=nsplits)
        self.kf_nofalls = KFold(n_splits=nsplits)


        for stream in streams:
            h5features = h5py.File(stream + '_features_' + self.id + '.h5', 'r')
            h5labels = h5py.File(stream + '_labels_' + self.id + '.h5', 'r')
            self.all_features = h5features[self.features_key]
            self.all_labels = np.asarray(h5labels[self.labels_key])
            self.falls = np.asarray(np.where(self.all_labels==0)[0])
            self.no_falls = np.asarray(np.where(self.all_labels==1)[0])
            self.falls.sort()
            self.no_falls.sort()

            sensitivities = []
            specificities = []
            fars = []
            mdrs = []
            accuracies = []
           
            first = 0

            # CROSS-VALIDATION: Stratified partition of the dataset into 
            # train/test sets
            # todo : split this line
            for (train_falls, test_falls), (train_nofalls, test_nofalls) in zip(self.kf_falls.split(self.all_features[self.falls, ...]), self.kf_nofalls.split(self.all_features[self.no_falls, ...])):

                train_falls = np.asarray(train_falls)
                test_falls = np.asarray(test_falls)
                train_nofalls = np.asarray(train_nofalls)
                test_nofalls = np.asarray(test_nofalls)

                # todo: change this X, _y, X2 and _y2 variables name
                X = np.concatenate((self.all_features[train_falls, ...], 
                    self.all_features[train_nofalls, ...]))
                _y = np.concatenate((self.all_labels[train_falls, ...],
                    self.all_labels[train_nofalls, ...]))
                X2 = np.concatenate((self.all_features[test_falls, ...],
                    self.all_features[test_nofalls, ...]))
                _y2 = np.concatenate((self.all_labels[test_falls, ...], 
                    self.all_labels[test_nofalls, ...]))   
                
                self.set_classifier_vgg16() 

                # ==================== TRAINING ========================     
                # weighting of each class: only the fall class gets a different
                # weight
                class_weight = {0: self.weight_0, 1: 1}
                # Batch training
                if self.mini_batch_size == 0:
                    history = self.classifier.fit(X,_y, validation_data=(X2,_y2), 
                            batch_size=X.shape[0], epochs=self.epochs, 
                            shuffle='batch', class_weight=class_weight)
                else:
                    history = self.classifier.fit(X, _y, validation_data=(X2,_y2), 
                            batch_size=self.mini_batch_size, nb_epoch=self.epochs, 
                            shuffle='batch', class_weight=class_weight)

                exp = 'lr{}_batchs{}_batchnorm{}_w0_{}'.format(self.learning_rate, self.mini_batch_size, self.batch_norm, self.weight_0)
                self.plot_training_info(exp, ['accuracy', 'loss'], True, 
                                   history.history)

                # Store only the first classifier
                if first == 0:
                    self.classifier.save(stream + '_classifier_' + self.id + '.h5')
                    first = 1

                # ==================== EVALUATION ======================== 
                predicted = self.classifier.predict(np.asarray(X2))
                self.evaluate_threshold(predicted, _y2, sensitivities, 
                specificities, fars, mdrs, accuracies)
                
            print('5-FOLD CROSS-VALIDATION RESULTS ===================')
            print("Sensitivity: %.2f%% (+/- %.2f%%)" % (np.mean(sensitivities), 
                                                        np.std(sensitivities)))
            print("Specificity: %.2f%% (+/- %.2f%%)" % (np.mean(specificities),
                                                        np.std(specificities)))
            print("FAR: %.2f%% (+/- %.2f%%)" % (np.mean(fars), np.std(fars)))
            print("MDR: %.2f%% (+/- %.2f%%)" % (np.mean(mdrs), np.std(mdrs)))
            print("Accuracy: %.2f%% (+/- %.2f%%)" % (np.mean(accuracies), 
                                                     np.std(accuracies)))

    def video_random_split(self, stream, test_size):
        random.seed(42)
        f = h5py.File(stream + '_features_' + self.id + '.h5', 'r')
        all_f = np.asarray(f[self.features_key])
        s = h5py.File(stream + '_samples_'+ self.id + '.h5', 'r')
        all_s = np.asarray(s[self.samples_key])
        l = h5py.File(stream + '_labels_' + self.id + '.h5', 'r')
        all_l = np.asarray(l[self.labels_key])
        num = h5py.File(stream + '_num_' + self.id + '.h5', 'r')
        all_num = np.asarray(num[self.num_key])


        test_videos = [ [] for x in range(len(all_num)) ]
        train_videos = [ [] for x in range(len(all_num)) ]

        start = 0

        for i in range(len(all_num)):
            for j in range(int(all_num[i][0] * test_size)):

                x = random.randint(start, start + all_num[i][0]-1)
                while x in test_videos[i]:
                    x = random.randint(start, start + all_num[i][0]-1)

                test_videos[i].append(x)

            for j in range(start, start + all_num[i][0]):
                if j not in test_videos[i]:
                    train_videos[i].append(j)
            start += all_num[i][0]

        for video in range(1, len(all_s)):
            all_s[video] += all_s[video-1]

        X_train = []
        X_test = []
        y_train = []
        y_test = []

        # For every class
        c_test = 0
        c_train = 0
        for c in range(len(all_num)):

            # Pass through test_videos from c-th class
            for video in test_videos[c]:
                if video != 0:
                    tam = len(list(range(all_s[video-1][0], all_s[video][0])))
                    X_test[c_test:c_test+tam] = all_f[all_s[video-1][0]:all_s[video][0]]
                    y_test[c_test:c_test+tam] = all_l[all_s[video-1][0]:all_s[video][0]]
                else:
                    tam = len(list(range(0, all_s[video][0])))
                    X_test[c_test:c_test+tam] = all_f[0:all_s[video][0]]
                    y_test[c_test:c_test+tam] = all_l[0:all_s[video][0]]
                c_test+=tam
                
            # Pass through traint_videos from c-th class
            for video in train_videos[c]:
                if video != 0:
                    tam = len(list(range(all_s[video-1][0], all_s[video][0])))
                    X_train[c_train:c_train+tam] = all_f[all_s[video-1][0]:all_s[video][0]]
                    y_train[c_train:c_train+tam] = all_l[all_s[video-1][0]:all_s[video][0]]
                else:
                    tam = len(list(range(0, all_s[video][0])))
                    X_train[c_train:c_train+tam] = all_f[0:all_s[video][0]]
                    y_train[c_train:c_train+tam] = all_l[0:all_s[video][0]]
                c_train+=tam

        f.close()
        l.close()
        num.close()
        return np.asarray(X_train), np.asarray(X_test), np.asarray(y_train), np.asarray(y_test), train_videos, test_videos 

    def train(self, streams):
   
        VGG16 = True
        predicteds = []
        train_predicteds = []
        temporal = 'temporal' in streams
        len_RGB = 0
        train_len_RGB = 0
        len_STACK = 0
        train_len_STACK = 0
        for stream in streams:

            if VGG16:
                self.set_classifier_vgg16()
            else:
                self.set_classifier_resnet50()

            h5features = h5py.File(stream + '_features_' + self.id + '.h5', 'r')
            h5labels = h5py.File(stream + '_labels_' + self.id + '.h5', 'r')
            h5samples = h5py.File(stream + '_samples_' + self.id + '.h5', 'r')
            h5num = h5py.File(stream + '_num_' + self.id + '.h5', 'r')
            self.all_features = h5features[self.features_key]
            self.all_labels = np.asarray(h5labels[self.labels_key])
            self.all_samples = np.asarray(h5samples[self.samples_key])
            self.all_num = np.asarray(h5num[self.num_key])

            sensitivities = []
            specificities = []
            fars = []
            mdrs = []
            accuracies = []

            test_size = 0.2

            X_train, X_test, y_train, y_test, train_videos, test_videos = self.video_random_split(stream, test_size)
            #X_train, X_test, y_train, y_test = train_test_split(np.asarray(self.all_features), 
            #                        np.asarray(self.all_labels), test_size=0.2)

            # ==================== TRAINING ========================     
            # weighting of each class: only the fall class gets a different weight
            class_weight = {0: self.weight_0, 1: 1}
            # Batch training
            if self.mini_batch_size == 0:
                history = self.classifier.fit(X_train, y_train, 
                        validation_data=(X_test, y_test), 
                        batch_size=X_train.shape[0], epochs=self.epochs, 
                        shuffle='batch', class_weight=class_weight)
            else:
                history = self.classifier.fit(X_train, y_train, 
                        validation_data=(X_test, y_test), 
                        batch_size=self.mini_batch_size, nb_epoch=self.epochs, 
                        shuffle=True, class_weight=class_weight, verbose=2)

            exp = 'lr{}_batchs{}_batchnorm{}_w0_{}'.format(self.learning_rate, self.mini_batch_size, self.batch_norm, self.weight_0)
            self.plot_training_info(exp, ['accuracy', 'loss'], True, 
                               history.history)

            self.classifier.save(stream + '_classifier_' + self.id + '.h5')
            predicted = np.asarray(self.classifier.predict(np.asarray(X_test)))
            train_predicted = np.asarray(self.classifier.predict(np.asarray(X_train)))

            if stream == 'spatial' or stream == 'pose':
                len_RGB = len(y_test)
                train_len_RGB = len(y_train)

                print('EVALUATE WITH %s' % (stream))

                # ==================== EVALUATION ======================== 
                self.evaluate_threshold(predicted, y_test, sensitivities, 
                specificities, fars, mdrs, accuracies)

                if not temporal:
                    Truth = y_test
                    predicteds.append(predicted)
                    train_predicteds.append(train_predicted)
                else:    
                    Truth = y_test
                    pos = 0
                    train_pos = 0
                    index = []
                    train_index = []
                    for c in range(len(self.all_num)):  
                        for x in test_videos[c]:
                            num_samples = self.all_samples[x][0]
                            index += list(range(pos + num_samples - self.sliding_height, pos + num_samples))
                            pos+=num_samples
                        for x in train_videos[c]:
                            num_samples = self.all_samples[x][0]
                            train_index += list(range(train_pos + num_samples - self.sliding_height, train_pos + num_samples))
                            train_pos+=num_samples

                    Truth = np.delete(Truth, index)
                    clean_predicted = np.delete(predicted, index)
                    train_clean_predicted = np.delete(train_predicted, train_index)
                    predicteds.append(clean_predicted)
                    train_predicteds.append(train_clean_predicted)

            elif stream == 'temporal':

                # Checking if temporal is the only stream
                if len(streams) == 1:
                    Truth = y_test

                len_STACK = len(y_test)
                train_len_STACK = len(y_train)
                print('EVALUATE WITH %s' % (stream))

                predicteds.append(np.copy(predicted)) 
                train_predicteds.append(np.copy(train_predicted)) 
                # ==================== EVALUATION ======================== 
                self.evaluate_threshold(predicted, y_test, sensitivities, 
                specificities, fars, mdrs, accuracies)
                
        if temporal:
            X_train, X_test, y_train, y_test, train_videos, test_videos = self.video_random_split('temporal', test_size)
            avg_predicted = np.zeros(len_STACK, dtype=np.float)
            train_avg_predicted = np.zeros(train_len_STACK, dtype=np.float)
            clf_train_predicteds = np.zeros( (train_len_STACK, len(streams)) )

            for j in range(len_STACK):
                for i in range(len(streams)):
                    avg_predicted[j] += predicteds[i][j] 

                avg_predicted[j] /= (len(streams))

            for j in range(train_len_STACK):
                for i in range(len(streams)):
                    train_avg_predicted[j] += train_predicteds[i][j] 

                train_avg_predicted[j] /= (len(streams))
             
            for j in range(train_len_STACK):
                clf_train_predicteds[j] = [item[j] for item in train_predicteds]
        else:
            X_train, X_test, y_train, y_test, train_videos, test_videos = self.video_random_split('pose', test_size)
            avg_predicted = np.zeros(len_RGB, dtype=np.float)
            train_avg_predicted = np.zeros(train_len_RGB, dtype=np.float)
            clf_train_predicteds = np.zeros( (train_len_RGB, len(streams)) )
            for j in range(len_RGB):
                for i in range(len(streams)):
                    avg_predicted[j] += predicteds[i][j] 

                avg_predicted[j] /= (len(streams))

            for j in range(train_len_RGB):
                for i in range(len(streams)):
                    train_avg_predicted[j] += train_predicteds[i][j] 

                train_avg_predicted[j] /= (len(streams))

            for j in range(train_len_RGB):
                clf_train_predicteds[j] = [item[j] for item in train_predicteds]
        
        sensitivities = []
        specificities = []
        fars = []
        mdrs = []
        accuracies = []
        print('EVALUATE WITH average and threshold')
        self.evaluate_threshold(np.array(avg_predicted, copy=True), Truth, sensitivities,
                specificities, fars, mdrs, accuracies)

        clf_continuous = svm.SVC()

        clf_continuous.fit(clf_train_predicteds, y_train.ravel())
        avg_continuous = np.array(avg_predicted, copy=True)
        for i in range(len(avg_continuous)):
            avg_continuous[i] = clf_continuous.predict(np.asarray([item[i] for item in predicteds]).reshape(1, -1))

        sensitivities = []
        specificities = []
        fars = []
        mdrs = []
        accuracies = []
        print('EVALUATE WITH continuous values and SVM')
        self.evaluate(avg_continuous, Truth, sensitivities,
                specificities, fars, mdrs, accuracies)

        clf_avg = svm.SVC()                                                                 
        clf_avg.fit(train_avg_predicted.reshape(-1, 1), y_train.ravel())
        for i in range(len(avg_predicted)):
            avg_predicted[i] = clf_avg.predict(avg_predicted[i])

        joblib.dump(clf_avg, 'svm_avg.pkl') 
        sensitivities = []
        specificities = []
        fars = []
        mdrs = []
        accuracies = []
        print('EVALUATE WITH average and SVM')
        self.evaluate(avg_predicted, Truth, sensitivities,
                specificities, fars, mdrs, accuracies)

    def evaluate_threshold(self, predicted, _y2, sensitivities, specificities,
    fars, mdrs, accuracies):

       for i in range(len(predicted)):
           if predicted[i] < self.threshold:
               predicted[i] = 0
           else:
               predicted[i] = 1
       #  Array of predictions 0/1

       self.evaluate(predicted, _y2, sensitivities, specificities, fars, mdrs, accuracies)

    def evaluate(self, predicted, _y2, sensitivities, 
    specificities, fars, mdrs, accuracies):

        predicted = np.asarray(predicted).astype(int)
        # Compute metrics and print them
        cm = confusion_matrix(_y2, predicted,labels=[0,1])
        tp = cm[0][0]
        fn = cm[0][1]
        fp = cm[1][0]
        tn = cm[1][1]
        tpr = tp/float(tp+fn)
        fpr = fp/float(fp+tn)
        fnr = fn/float(fn+tp)
        tnr = tn/float(tn+fp)
        precision = tp/float(tp+fp)
        recall = tp/float(tp+fn)
        specificity = tn/float(tn+fp)
        f1 = 2*float(precision*recall)/float(precision+recall)
        accuracy = accuracy_score(_y2, predicted)

        print('TP: {}, TN: {}, FP: {}, FN: {}'.format(tp,tn,fp,fn))
        print('TPR: {}, TNR: {}, FPR: {}, FNR: {}'.format(tpr,tnr,fpr,fnr))   
        print('Sensitivity/Recall: {}'.format(recall))
        print('Specificity: {}'.format(specificity))
        print('Precision: {}'.format(precision))
        print('F1-measure: {}'.format(f1))
        print('Accuracy: {}'.format(accuracy))

        # Store the metrics for this epoch
        sensitivities.append(tp/float(tp+fn))
        specificities.append(tn/float(tn+fp))
        fars.append(fpr)
        mdrs.append(fnr)
        accuracies.append(accuracy)

    def set_classifier_resnet50(self):
        extracted_features = Input(shape=(self.num_features,), dtype='float32',
                                   name='input')
        if self.batch_norm:
            x = BatchNormalization(axis=-1, momentum=0.99, 
                                   epsilon=0.001)(extracted_features)
            x = Activation('relu')(x)
        else:
            x = ELU(alpha=1.0)(extracted_features)
       
        x = Dropout(0.9)(x)
        x = Dense(1, name='predictions', kernel_initializer='glorot_uniform')(x)
        x = Activation('sigmoid')(x)

        adam = Adam(lr=self.learning_rate, beta_1=0.9, beta_2=0.999, 
                    epsilon=1e-08, decay=0.0005)

        self.classifier = Model(input=extracted_features, output=x, 
                           name='classifier')
        self.classifier.compile(optimizer=adam, loss='binary_crossentropy',
                           metrics=['accuracy'])

    def set_classifier_vgg16(self):
        extracted_features = Input(shape=(self.num_features,), dtype='float32',
                                   name='input')
        if self.batch_norm:
            x = BatchNormalization(axis=-1, momentum=0.99, 
                                   epsilon=0.001)(extracted_features)
            x = Activation('relu')(x)
        else:
            x = ELU(alpha=1.0)(extracted_features)
       
        x = Dropout(0.9)(x)
        x = Dense(self.num_features, name='fc2', 
                  kernel_initializer='glorot_uniform')(x)
        if self.batch_norm:
            x = BatchNormalization(axis=-1, momentum=0.99, epsilon=0.001)(x)
            x = Activation('relu')(x)
        else:
            x = ELU(alpha=1.0)(x)
        x = Dropout(0.8)(x)
        x = Dense(1, name='predictions', 
                  kernel_initializer='glorot_uniform')(x)
        x = Activation('sigmoid')(x)
        
        adam = Adam(lr=self.learning_rate, beta_1=0.9, beta_2=0.999, 
                    epsilon=1e-08, decay=0.0005)

        self.classifier = Model(input=extracted_features, output=x, 
                           name='classifier')
        self.classifier.compile(optimizer=adam, loss='binary_crossentropy',
                           metrics=['accuracy'])

    def plot_training_info(self, case, metrics, save, history):
        '''
        Function to create plots for train and validation loss and accuracy
        Input:
        * case: name for the plot, an 'accuracy.png' or 'loss.png' will be concatenated after the name.
        * metrics: list of metrics to store: 'loss' and/or 'accuracy'
        * save: boolean to store the plots or only show them.
        * history: History object returned by the Keras fit function.
        '''
        plt.ioff()
        if 'accuracy' in metrics:     
            fig = plt.figure()
            plt.plot(history['acc'])
            plt.plot(history['val_acc'])
            plt.title('model accuracy')
            plt.ylabel('accuracy')
            plt.xlabel('epoch')
            plt.legend(['train', 'val'], loc='upper left')
            if save == True:
                plt.savefig(case + 'accuracy.png')
                plt.gcf().clear()
            else:
                plt.show()
            plt.close(fig)

        # summarize history for loss
        if 'loss' in metrics:
            fig = plt.figure()
            plt.plot(history['loss'])
            plt.plot(history['val_loss'])
            plt.title('model loss')
            plt.ylabel('loss')
            plt.xlabel('epoch')
            #plt.ylim(1e-3, 1e-2)
            plt.yscale("log")
            plt.legend(['train', 'val'], loc='upper left')
            if save == True:
                plt.savefig(case + 'loss.png')
                plt.gcf().clear()
            else:
                plt.show()
            plt.close(fig)

if __name__ == '__main__':
    print("***********************************************************",
            file=sys.stderr)
    print("             SEMANTIX - UNICAMP DATALAB 2018", file=sys.stderr)
    print("***********************************************************",
            file=sys.stderr)
    print("For a simple training -nsplits flag isn't used.", file = sys.stderr)
    print("For a cross-training set -nsplits <k>, with k beeing the", file=sys.stderr)
    print("number of folders you want to split up your data.", file=sys.stderr)
    print("***********************************************************", 
            file=sys.stderr)

    argp = argparse.ArgumentParser(description='Do training tasks')
    argp.add_argument("-actions", dest='actions', type=str, nargs=1,
            help='Usage: -actions train or -actions cross-train', required=True)

    '''
        todo: make this weight_0 (w0) more general for multiple classes
    '''

    '''
        todo: verify if all these parameters are really required
    '''

    argp.add_argument("-streams", dest='streams', type=str, nargs='+',
            help='Usage: -streams spatial temporal (to use 2 streams example)',
            required=True)
    argp.add_argument("-thresh", dest='thresh', type=float, nargs=1,
            help='Usage: -thresh <x> (0<=x<=1)', required=True)
    argp.add_argument("-ep", dest='ep', type=int, nargs=1,
            help='Usage: -ep <num_of_epochs>', required=True)
    argp.add_argument("-lr", dest='lr', type=float, nargs=1,
            help='Usage: -lr <learning_rate_value>', required=True)
    argp.add_argument("-w0", dest='w0', type=float, nargs=1,
            help='Usage: -w0 <weight_for_fall_class>', required=True)
    argp.add_argument("-mini_batch", dest='mini_batch', type=int, nargs=1,
            help='Usage: -mini_batch <mini_batch_size>', required=True)
    argp.add_argument("-id", dest='id', type=str, nargs=1,
        help='Usage: -id <identifier_to_this_features_and_classifier>', 
        required=True)
    argp.add_argument("-batch_norm", dest='batch_norm', type=bool, nargs=1,
        help='Usage: -batch_norm <True/False>', required=True)
    argp.add_argument("-nsplits", dest='nsplits', type=int, nargs=1, 
    help='Usage: -nsplits <K: many splits you want (>1)>', required=False)

    try:
        args = argp.parse_args()
    except:
        argp.print_help(sys.stderr)
        exit(1)

    train = Train(args.thresh[0], args.ep[0], args.lr[0], 
            args.w0[0], args.mini_batch[0], args.id[0], args.batch_norm[0])

    if args.actions[0] == 'train':
        train.train(args.streams)
    elif args.actions[0] == 'cross-train':
        if args.nsplits == None:
            print("***********************************************************", 
                file=sys.stderr)
            print("You're performing a cross-traing but not giving -nsplits value")
            print("***********************************************************", 
                file=sys.stderr)
            
        else:
            train.cross_train(args.streams, args.nsplits[0])
    else:
        '''
        Invalid value for actions
        '''
        parser.print_help(sys.stderr)
        exit(1)

'''
    todo: criar excecoes para facilitar o uso
'''

'''
    todo: use model parameter to load model for training
'''

'''
    todo: nomes diferentes para classificadores
'''
