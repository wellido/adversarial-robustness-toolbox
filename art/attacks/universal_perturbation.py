from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import random

import numpy as np

from art.attacks.attack import Attack
from art.utils import projection

logger = logging.getLogger(__name__)


class UniversalPerturbation(Attack):
    """
    Implementation of the attack from Moosavi-Dezfooli et al. (2016). Computes a fixed perturbation to be applied to all
    future inputs. To this end, it can use any adversarial attack method. Paper link: https://arxiv.org/abs/1610.08401
    """
    attacks_dict = {'carlini': 'art.attacks.carlini.CarliniL2Method',
                    'deepfool': 'art.attacks.deepfool.DeepFool',
                    'fgsm': 'art.attacks.fast_gradient.FastGradientMethod',
                    'newtonfool': 'art.attacks.newtonfool.NewtonFool',
                    'jsma': 'art.attacks.saliency_map.SaliencyMapMethod',
                    'vat': 'art.attacks.virtual_adversarial.VirtualAdversarialMethod'
                    }
    attack_params = Attack.attack_params + ['attacker', 'attacker_params', 'delta', 'max_iter', 'eps', 'norm']

    def __init__(self, classifier, expectation_over_transformations=None, attacker='deepfool', attacker_params=None,
                 delta=0.2, max_iter=20, eps=10.0, norm=np.inf):
        """
        :param classifier: A trained model.
        :type classifier: :class:`Classifier`
        :param expectation_over_transformations: An expectation over transformations to be applied when computing 
                                                 classifier gradients.
        :type expectation_over_transformations: :class:`ExpectationOverTransformations`
        :param attacker: Adversarial attack name. Default is 'deepfool'. Supported names: 'carlini', 'deepfool', 'fgsm',
                'newtonfool', 'jsma', 'vat'.
        :type attacker: `str`
        :param attacker_params: Parameters specific to the adversarial attack.
        :type attacker_params: `dict`
        :param delta: desired accuracy
        :type delta: `float`
        :param max_iter: The maximum number of iterations for computing universal perturbation.
        :type max_iter: `int`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param norm: Order of the norm. Possible values: np.inf, 2 (default is np.inf)
        :type norm: `int`
        """
        super(UniversalPerturbation, self).__init__(classifier)
        kwargs = {'attacker': attacker,
                  'attacker_params': attacker_params,
                  'delta': delta,
                  'max_iter': max_iter,
                  'eps': eps,
                  'norm': norm
                  }
        self.set_params(**kwargs)

    def generate(self, x, **kwargs):
        """
        Generate adversarial samples and return them in an array.

        :param x: An array with the original inputs.
        :type x: `np.ndarray`
        :param attacker: Adversarial attack name. Default is 'deepfool'. Supported names: 'carlini', 'deepfool', 'fgsm',
                'newtonfool', 'jsma', 'vat'.
        :type attacker: `str`
        :param attacker_params: Parameters specific to the adversarial attack.
        :type attacker_params: `dict`
        :param delta: desired accuracy
        :type delta: `float`
        :param max_iter: The maximum number of iterations for computing universal perturbation.
        :type max_iter: `int`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param norm: Order of the norm. Possible values: np.inf, 1 and 2 (default is np.inf).
        :type norm: `int`
        :return: An array holding the adversarial examples.
        :rtype: `np.ndarray`
        """
        logger.info('Computing universal perturbation based on %s attack.', self.attacker)

        self.set_params(**kwargs)

        # Init universal perturbation
        v = 0
        fooling_rate = 0.0
        nb_instances = len(x)

        # Instantiate the middle attacker and get the predicted labels
        attacker = self._get_attack(self.attacker, self.attacker_params)
        pred_y = self.predict(x, logits=False)
        pred_y_max = np.argmax(pred_y, axis=1)

        # Start to generate the adversarial examples
        nb_iter = 0
        while fooling_rate < 1. - self.delta and nb_iter < self.max_iter:
            # Go through all the examples randomly
            rnd_idx = random.sample(range(nb_instances), nb_instances)

            # Go through the data set and compute the perturbation increments sequentially
            for j, ex in enumerate(x[rnd_idx]):
                xi = ex[None, ...]

                f_xi = self.predict(xi + v, logits=True)
                fk_i_hat = np.argmax(f_xi[0])
                fk_hat = np.argmax(pred_y[rnd_idx][j])

                if fk_i_hat == fk_hat:
                    # Compute adversarial perturbation
                    adv_xi = attacker.generate(xi + v)
                    adv_f_xi = self.predict(adv_xi, logits=True)
                    adv_fk_i_hat = np.argmax(adv_f_xi[0])

                    # If the class has changed, update v
                    if fk_i_hat != adv_fk_i_hat:
                        v += adv_xi - xi

                        # Project on L_p ball
                        v = projection(v, self.eps, self.norm)
            nb_iter += 1

            # Compute the error rate
            adv_x = x + v
            adv_y = np.argmax(self.predict(adv_x, logits=False))
            fooling_rate = np.sum(pred_y_max != adv_y) / nb_instances

        self.fooling_rate = fooling_rate
        self.converged = (nb_iter < self.max_iter)
        self.v = v
        logger.info('Success rate of universal perturbation attack: %.2f%%', fooling_rate)

        return adv_x

    def set_params(self, **kwargs):
        """
        Take in a dictionary of parameters and applies attack-specific checks before saving them as attributes.

        :param attacker: Adversarial attack name. Default is 'deepfool'. Supported names: 'carlini', 'deepfool', 'fgsm',
                'newtonfool', 'jsma', 'vat'.
        :type attacker: `str`
        :param attacker_params: Parameters specific to the adversarial attack.
        :type attacker_params: `dict`
        :param delta: desired accuracy
        :type delta: `float`
        :param max_iter: The maximum number of iterations for computing universal perturbation.
        :type max_iter: `int`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param norm: Order of the norm. Possible values: np.inf, 2 (default is np.inf)
        :type norm: `int`
        """
        super(UniversalPerturbation, self).set_params(**kwargs)

        if not isinstance(self.delta, (float, int)) or self.delta < 0 or self.delta > 1:
            raise ValueError("The desired accuracy must be in the range [0, 1].")

        if not isinstance(self.max_iter, (int, np.int)) or self.max_iter <= 0:
            raise ValueError("The number of iterations must be a positive integer.")

        if not isinstance(self.eps, (float, int)) or self.eps <= 0:
            raise ValueError("The eps coefficient must be a positive float.")

        return True

    def _get_attack(self, a_name, params=None):
        """
        Get an attack object from its name.

        :param a_name: attack name.
        :type a_name: `str`
        :param params: attack params.
        :type params: `dict`
        :return: attack object
        :rtype: `object`
        """
        try:
            attack_class = self._get_class(self.attacks_dict[a_name])
            a_instance = attack_class(self.classifier)

            if params:
                a_instance.set_params(**params)

            return a_instance

        except KeyError:
            raise NotImplementedError("{} attack not supported".format(a_name))

    @staticmethod
    def _get_class(class_name):
        """
        Get a class module from its name.

        :param class_name: Full name of a class.
        :type class_name: `str`
        :return: The class `module`.
        :rtype: `module`
        """
        sub_mods = class_name.split(".")
        module_ = __import__(".".join(sub_mods[:-1]), fromlist=sub_mods[-1])
        class_module = getattr(module_, sub_mods[-1])

        return class_module
