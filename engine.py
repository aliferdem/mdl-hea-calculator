import itertools
import json
import math

import numpy as np


class Engine:
    def __init__(self):
        self.R = 8.314462618  # J/(mol·K), universal gas constant
        self.mixing_enthalpy_data = self._read("data/mixing_enthalpy_data.json")
        self.fusion_enthalpy_data = self._read("data/fusion_enthalpy_data.json")
        self.periodic_table = self._read("data/periodic_table.json")

    def _read(self, file_name: str):
        with open(file_name, "r") as f:
            return json.load(f)

    def _density(self, selected_elements):
        total_weight = sum(at_p * float(self.periodic_table[el]["properties"]["atomic_weight"]) for el, at_p in selected_elements.items())
        total_volume = sum(at_p * float(self.periodic_table[el]["properties"]["atomic_volume"]) for el, at_p in selected_elements.items())

        density = total_weight / total_volume
        return density
    
    def _delta(self, selected_elements):
        average_atomic_radius = sum(at_p * float(self.periodic_table[el]["properties"]["atomic_radius"]) for el, at_p in selected_elements.items())

        _delta = 0
        for element, atomic_percent in selected_elements.items():
            atomic_radius = float(self.periodic_table[element]["properties"]["atomic_radius"])
            _delta += atomic_percent * (1 - (atomic_radius / average_atomic_radius))**2

        self.delta = math.sqrt(_delta) * 100
        return self.delta
    
    def _gamma(self, selected_elements):
        average_atomic_radius = sum(at_p * float(self.periodic_table[el]["properties"]["atomic_radius"]) for el, at_p in selected_elements.items())
        atomic_radius_list = [float(self.periodic_table[element]["properties"]["atomic_radius"]) for element in selected_elements.keys()]

        smallest_solid_angle = (1 - math.sqrt((((min(atomic_radius_list) + average_atomic_radius) ** 2) - (average_atomic_radius ** 2)) /
                                            ((min(atomic_radius_list) + average_atomic_radius) ** 2)))
        largest_solid_angle = (1 - math.sqrt((((max(atomic_radius_list) + average_atomic_radius) ** 2) - (average_atomic_radius ** 2)) /
                                           ((max(atomic_radius_list) + average_atomic_radius) ** 2)))
        
        self.gamma = smallest_solid_angle / largest_solid_angle
        return self.gamma
    
    def _enthalpy_of_mixing(self, selected_elements):
        self.pair_list = list(itertools.combinations(selected_elements.keys(), 2))
        pair_enthalpy = [self.mixing_enthalpy_data.get(pair[0], {}).get(pair[1]) or
                         self.mixing_enthalpy_data.get(pair[1], {}).get(pair[0], "NaN")
                         for pair in self.pair_list]
        
        pair_enthalpy = [float(enthalpy) if enthalpy != "NaN" else 0.0 for enthalpy in pair_enthalpy]
        
        pair_at_p = [(selected_elements[pair[0]]) * (selected_elements[pair[1]])
                     for pair in self.pair_list]
        
        self.mixing_enthalpy = 4 * sum([at_p * enthalpy for at_p, enthalpy in zip(pair_at_p, pair_enthalpy)])
        return self.mixing_enthalpy
    
    def _mixing_entropy(self, selected_elements):
        self.mixing_entropy = -self.R * sum(frac * (0 if frac == 0 else np.log(frac)) for frac in selected_elements.values())
        return self.mixing_entropy

    def _melting_temperature(self, selected_elements):
        self.melting_temperature = sum(at_p * float(self.periodic_table[el]["properties"]["melting_point"]) for el, at_p in selected_elements.items())
        return self.melting_temperature

    def _model6(self, selected_elements):
        delta_Hf_alloy = []
        pair_list = list(itertools.combinations(selected_elements.keys(), 2))
        for pair in pair_list:
            if pair[0] in self.fusion_enthalpy_data and pair[1] in self.fusion_enthalpy_data[pair[0]]:
                delta_Hf_alloy.append(self.fusion_enthalpy_data[pair[0]][pair[1]])

        annealing_temperature = self.melting_temperature * 0.55
        model6 = "SS" if -1 * annealing_temperature * self.mixing_entropy * 1.04 * 10 ** -2 <= min(delta_Hf_alloy) \
                                    and min(delta_Hf_alloy) <= 37 else "IM"
        return model6

    def calculate(self, selected_elements, restriction_values):
        try:
            values = dict()
            values["density"] = self._density(selected_elements)
            values["delta"] = self._delta(selected_elements)
            values["gamma"] = self._gamma(selected_elements)
            values["enthalpy_of_mixing"] = self._enthalpy_of_mixing(selected_elements)

            vec = sum(at_p * float(self.periodic_table[el]["properties"]["nvalence"]) for el, at_p in selected_elements.items())
            mixing_entropy = -self.R * sum(frac * (0 if frac == 0 else np.log(frac)) for frac in selected_elements.values())
            melting_temperature = math.ceil(sum(frac * float(self.periodic_table[el]["properties"]["melting_point"]) 
                                                    for el, frac in selected_elements.items()))
            omega = ((melting_temperature * mixing_entropy) / (abs(self.mixing_enthalpy) * 1000) if self.mixing_enthalpy != 0 else 10 ** 10)

            values["vec"] = vec
            values["mixing_entropy"] = mixing_entropy
            values["melting_temp"] = melting_temperature
            values["omega"] = omega

            ########## Crystal Str. ##########
            if 2.5 <= vec <= 3.5:
                microstructure = "HCP"
            elif vec >= 8.0:
                microstructure = "FCC"
            elif vec <= 6.87:
                microstructure = "BCC"
            else:
                microstructure = "BCC + FCC"

            values["cstr"] = microstructure
        except:
            raise ValueError("Not enough data")

        ############### MODEL 1 ###############
        try:
            values["model1"] = "SS" if omega >= 1.1 and 0 < self.delta < 6.6 \
                else "IM"
        except:
            values["model1"] = "N/A"

        ############### MODEL 2 ###############
        try:
            values["model2"] = "SS" if 0 < self.delta < 6.6 and 3.2 > self.mixing_enthalpy > -11.6 \
                else "IM"
        except:
            values["model2"] = "N/A"


        ############### MODEL 3 ###############
        try:
            values["model3"] = "SS" if self.gamma < 1.175 and 3.2 > self.mixing_enthalpy > -11.6 \
                else "IM"
        except:
            values["model3"] = "N/A"


            ############### MODEL 4 ###############
        try:
            try:
                _lambda = mixing_entropy / (self.delta ** 2)

                if _lambda < 0.24 and self._enthalpy_of_mixing(selected_elements) < -15:
                    model4 = "IM"
                elif 0.24 <= _lambda <= 0.96 and -15<= self._enthalpy_of_mixing(selected_elements) <= -5:
                    model4 = "SS+IM"
                elif 0.96 <= _lambda and -5<= self._enthalpy_of_mixing(selected_elements) <= 0:
                    model4 = "SS"
                elif 0.96 <= _lambda and 0< self._enthalpy_of_mixing(selected_elements):
                    model4 = "SS+SS"
                
                values["model4"] = model4
            except:
                _lambda = mixing_entropy / (self.delta ** 2)
                if _lambda < 0.24:
                    model4 = "[IM]"
                elif 0.96 < _lambda:
                    model4 = "[SS]"
                else:
                    model4 = "[Mixed]"
                
                values["model4"] = model4
        except:
            values["model4"] = "N/A"


            ############### MODEL 6 ###############
        try:
            delta_Hf_alloy = []
            for pair in self.pair_list:
                if pair[0] in self.fusion_enthalpy_data and pair[1] in self.fusion_enthalpy_data[pair[0]]:
                    delta_Hf_alloy.append(self.fusion_enthalpy_data[pair[0]][pair[1]])

            annealing_temperature = melting_temperature * 0.55
            values["model6"] = "SS" if -1 * annealing_temperature * mixing_entropy * 1.04 * 10 ** -2 <= min(delta_Hf_alloy) \
                                    and min(delta_Hf_alloy) <= 37 else "IM"
        except:
            values["model6"] = "N/A"


            ############### MODEL 7 ###############
        try:
            delta_Hf_IM = []

            for pair in self.pair_list:
                pair_fraction = 0
                if pair[0] in self.fusion_enthalpy_data and pair[1] in self.fusion_enthalpy_data[pair[0]]:
                    if (pair[0], pair[1]) in self.pair_list:
                        pair_fraction = selected_elements[pair[0]] * selected_elements[pair[1]]
                    else:
                        pair_fraction = selected_elements[pair[1]] * selected_elements[pair[0]]
                    delta_Hf_IM.append((self.fusion_enthalpy_data[pair[0]][pair[1]], pair_fraction))

            delta_H_IM = 4 * sum((entry[0] * entry[1]) for entry in delta_Hf_IM) * 0.09648

            K2 = 0.6
            T_an = melting_temperature * 0.6

            omega_T = ((T_an * mixing_entropy) / (abs(self.mixing_enthalpy) * 1000) if self.mixing_enthalpy != 0 else 10 ** 10)
            K1_cr_T = ((omega_T) * (1 - K2)) + 1


            values["model7"] = "SS (Tₐₙ: " + str("%.1f" % T_an) + " K)" \
                                if K1_cr_T > ((delta_H_IM / self.mixing_enthalpy) if self.mixing_enthalpy != 0 else 10 ** 10) \
                                    else "IM  (Tₐₙ: " + str( "%.1f" % T_an) + " K)"
        except:
            values["model7"] = "N/A"

        meets_criteria = True

        if restriction_values:
            for property, restriction in restriction_values.items():
                if isinstance(restriction, dict):
                    min_value = float(restriction.get('min', None))
                    max_value = float(restriction.get('max', None))
                    if not (min_value <= float(values[property]) <= max_value):
                        meets_criteria = False
                        break
                else:
                    if restriction_values[property] != values[property]:
                        meets_criteria = False
                        break
            
        return values, meets_criteria

        
    def get_atomic_weight(self, element: str) -> float:
        return self.periodic_table[element]["properties"]["atomic_weight"]