#!/usr/bin/env python3
# Team TJ-MAM
from collections import defaultdict
import numpy as np
import pandas as pd

from keras.layers import Input
from keras.models import Model
from keras.optimizers import Adam
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import confusion_matrix, classification_report

from discriminator import Discriminator
from generator import Generator
from mysql import SQLConnector


try:
    import cPickle as pickle
except:
    import pickle


class GAN(object):

    def __init__(self, **kwargs):
        """ Constructor """
        self._defaults()
        self._args(kwargs)  # override defaults with args passed
        self.setup()
        self.build()

    def _defaults(self):
        """ Sets default variable values """
        self.attack_type = None
        self.discriminator = None
        self.generator = None
        self.gan = None

        # saved_states can be used to save states of a GAN, say
        # 5 of them so that the best can be saved when breaking out.
        self.saved_states = []
        self.confusion_matrix = None
        self.classification_report = None

        self.optimizer_learning_rate = 0.0002
        self.optimizer_beta = 0.5
        self.optimizer = Adam(self.optimizer_learning_rate, self.optimizer_beta)

        self.max_epochs = 7000
        self.batch_size = 255
        self.sample_size = 500

        self.valid = None
        self.fake = None
        self.X_train = None

        self.discriminator_layers = [
            (30, 'relu'),
            (15, 'relu')
        ]
        self.generator_layers = [0, 0, 0]
        self.generator_alpha: 0.5
        self.generator_momentum: 0.8

        self.confusion_matrix = None
        self.classification_report = None


        self.save_file = None

    def _args(self, kwargs):
        """ kwargs handler """
        for key, value in kwargs.items():
            if key == 'attack_type':
                self.attack_type = value
            elif key == 'max_epochs':
                self.max_epochs = value
            elif key == 'batch_size':
                self.batch_size = value
            elif key == 'sample_size':
                self.sample_size = value
            elif key == 'optimizer_learning_rate':
                self.optimizer_learning_rate = value
            elif key == 'optimizer_beta':
                self.optimizer_beta = value
            elif key == 'discriminator_layers':
                self.discriminator_layers = value
            elif key == 'generator_layers':
                self.generator_layers = value
            elif key == 'generator_alpha':
                self.generator_alpha = value
            elif key == 'generator_momentum':
                self.generator_momentum = value

    def setup(self):
        """ Setups the GAN """
        # TODO new method  called from init opt passed

        conn = SQLConnector()
        #data = conn.pull_best_results(attack='neptune', all=True)
        data = conn.pull_kdd99(self.attack_type, 500)
        data_test = conn.pull_kdd99(self.attack_type, 1) # get rid of
        dataframe = pd.DataFrame(data)

        print(dataframe.attack_type.unique)
        dataframe_test = pd.DataFrame(data_test) # rid 

        # https://stackoverflow.com/questions/24458645/label-encoding-across-multiple-columns-in-scikit-learn
        d = defaultdict(LabelEncoder)

        # fit is the encoded dataframe
        fit = dataframe.apply(lambda x: d[x.name].fit_transform(x))
        # dataset is fit as an ndarray (changing this cuases issues)
        dataset = fit.values


        print("===============================================")
        print("encoded:")
        print("===============================================")
        print(dataframe_test)

        # How to decode:
        print("===============================================")
        print("decoded:")
        print("===============================================")
        #decoded = fit.apply(lambda x: d[x.name].inverse_transform(x))
        #print(decoded)
        dataframe_test_decoded = dataframe_test.apply(lambda x:
                d[x.name].inverse_transform(x))
        print(dataframe_test_decoded)


        # to visually judge results
        print("Real " + self.attack_type + " attacks:")
        print(dataset[:2])

        # Set X as our input data and Y as our label
        self.X_train = dataset[:, 0:41].astype(float)
        Y_train = dataset[:, 41]

        # labels for data. 1 for valid attacks, 0 for fake (generated) attacks
        self.valid = np.ones((self.batch_size, 1))
        self.fake = np.zeros((self.batch_size, 1))


    def build(self):
        """ Build the GAN """
        # build the discriminator portion

        self.discriminator = Discriminator(self.discriminator_layers).get_model()
        self.discriminator.compile(
            loss='binary_crossentropy', optimizer=self.optimizer, metrics=['accuracy'])

        # build the generator portion
        gen_args = {
            'attack_type': self.attack_type,
            'layers': self.generator_layers,
            'alpha': self.generator_alpha,
            'momentum': self.generator_momentum
        }
        self.generator = Generator(**gen_args).get_model()

        # input and output of our combined model
        z = Input(shape=(41,))
        attack = self.generator(z)
        validity = self.discriminator(attack)

        # build combined model from generator and discriminator
        self.gan = Model(z, validity)
        self.gan.compile(loss='binary_crossentropy', optimizer=self.optimizer)

    def train(self):
        """ Trains the GAN system """
        # break condition for training (when diverging)
        loss_increase_count = 0
        prev_g_loss = 0

        for epoch in range(self.max_epochs):

            # ---------------------
            #  Train Discriminator
            # ---------------------

            # selecting batch_size random attacks from our training data
            idx = np.random.randint(0, self.X_train.shape[0], self.batch_size)
            attacks = self.X_train[idx]

            # generate a matrix of noise vectors
            noise = np.random.normal(0, 1, (self.batch_size, 41))

            # create an array of generated attacks
            gen_attacks = self.generator.predict(noise)

            # loss functions, based on what metrics we specify at model compile time
            d_loss_real = self.discriminator.train_on_batch(
                attacks, self.valid)
            d_loss_fake = self.discriminator.train_on_batch(
                gen_attacks, self.fake)
            d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)

            # generator loss function
            g_loss = self.gan.train_on_batch(noise, self.valid)
            if epoch % 100 == 0:
                print("%d [D loss: %f, acc.: %.2f%%] [G loss: %f] [Loss change:\
                      %.3f, Loss increases: %.0f]"
                      % (epoch, d_loss[0], 100 * d_loss[1], g_loss, g_loss - prev_g_loss, loss_increase_count))

            # if our generator loss increased this iteration, increment the counter by 1
            if (g_loss - prev_g_loss) > 0:
                loss_increase_count = loss_increase_count + 1
            else:
                loss_increase_count = 0  # otherwise, reset it to 0, we are still training effectively

            prev_g_loss = g_loss

            if loss_increase_count > 5:
                print('Stoping on iteration: ', epoch)
                break

            if epoch % 20 == 0:
                f = open("Results.txt", "a")
                np.savetxt("Results.txt", gen_attacks, fmt="%.0f")
                f.close()
                #self._push_results(epoch, gen_attacks)

        # peek at our results
        #results = self._pull_results(epoch)
        results = np.loadtxt("Results.txt")
        print("Generated " + self.attack_type + " attacks: ")
        print(results[:2])

    '''
    def _push_results(self, epoch, gen_attacks):
        """ Pushes results into database """
        conn = SQLConnector()
        print(gen_attacks)
        d = defaultdict(LabelEncoder)
        decoded = gen_attacks.apply(lambda x: d[x.name].inverse_transform(x))
        print(decoded)
        #conn.write_gens(gen_attacks)
        #conn.write_hyper(1, "2,3,4", 5, 80.3)
        #conn.write_gens(1, 1, 1, 0, "tcp", "ftp_data", "REJ", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0.00, 171, 62, 0.27, 0.02, 0.01, 0.03, 0.01, 0, 0.29, 0.02, 10)

    def _pull_results(self, epoch):
        """ Pulls results from database, returns list of lists """
        conn = SQLConnector()
        #TODO mysql sorts keys alphabetically 
        results = {}
        return results
        #conn.write_hyper(1, "2,3,4", 5, 80.3)
        #conn.write_gens(1, 1, 1, 0, "tcp", "ftp_data", "REJ", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0.00, 171, 62, 0.27, 0.02, 0.01, 0.03, 0.01, 0, 0.29, 0.02, 10)
        #np.loadtxt(self.results_path + self.results_name)
    '''

    def test(self):
        """ A GAN should know how to test itself and save its results into a confusion matrix. """
        # TODO
        pass

    ##########################################################################################
    # Uses Sklearn's confusion matrix maker
    # https://scikit-learn.org/stable/modules/generated/sklearn.metrics.confusion_matrix.html
    ##########################################################################################
    def make_confusion_matrix(self, y_true, y_pred):
        self.confusion_matrix = confusion_matrix(y_true, y_pred)
        self.classification_report = classification_report(y_true, y_pred)

    ################################################################################
    # Use these to save instances of a trained network with some desirable settings
    # Suggestion to save and load from the object's __dict__ taken from:
    # https://stackoverflow.com/questions/2709800/how-to-pickle-yourself
    ################################################################################
    def save_this(self, filename):
        '''
            Provide a basic filename to pickle this object for recovery later.
            Unlike the load function, this requires a save file, so that it will
            never accidentally overwrite a previous file.
        '''
        self.save_file = filename + '.pickle'
        with open(self.save_file, 'wb') as f:
            pickle.dump(self, f, pickle.HIGHEST_PROTOCOL)

    def load_state_from_file(self, filename=None):
        if not filename:
            if self.save_file:
                filename = self.save_file
            else:
                print("Error: No savefile for this object. \
                    \n Using save_this(filename) will set the save filename.")
                return
        with open(filename, 'rb') as f:
            tmp_dict = pickle.load(f)
            self.__dict__.update(tmp_dict.__dict__)
            f.close()


def main():
    """ Auto run main method """
    args = {
        'attack_type': "neptune",    # optional v
        'max_epochs': 7000,
        'batch_size': 255,
        'sample_size': 500,
        'optimizer_learning_rate': 0.0002,
        'optimizer_beta': 0.5,
        'discriminator_layers': [(30, 'relu'), (15, 'relu')],
        'generator_layers': [20, 40, 30],
        'generator_alpha': 0.5,
        'generator_momentum': 0.8
    }
    gan = GAN(**args)
    gan.train()


if __name__ == "__main__":
    main()
