import itertools
import json
import math

class Engine:
    def __init__(self, data_dir="data"):
        self.R = 8.314462618  # J/(mol·K), universal gas constant
        self.mixing_enthalpy_data = self._read(f"{data_dir}/mixing_enthalpy_data.json")
        self.fusion_enthalpy_data = self._read(f"{data_dir}/fusion_enthalpy_data.json")
        self.periodic_table = self._read(f"{data_dir}/periodic_table.json")

    def _read(self, file_name: str):
        with open(file_name, "r") as f:
            return json.load(f)

    def _excess_entropy_of_mixing(self, selected_elements, atomic_radii):
        # Passed pre-fetched radii as an argument to avoid redundant dictionary lookups
        elements = list(selected_elements.keys())
        c = {el: selected_elements[el] for el in elements}
        
        # Atomic diameter is twice the radius
        d = {el: atomic_radii[el] * 2 for el in elements}
        
        # Calculate the denominator for the fractional packing volume
        sum_cd3 = sum(c[el] * (d[el] ** 3) for el in elements)

        def calc_se_for_xi(xi):
            # Calculate individual packing fractions (xi_i)
            xi_i = {el: xi * (c[el] * (d[el] ** 3)) / sum_cd3 for el in elements}
            
            # Calculate y3
            y3_base = sum(((xi_i[el] / xi) ** (2/3)) * (c[el] ** (1/3)) for el in elements)
            y3 = y3_base ** 3
            
            y1 = 0.0
            y2 = 0.0
            
            # Calculate y1 and y2 using pair combinations
            for i, j in itertools.combinations(elements, 2):
                delta_ij = (((xi_i[i] * xi_i[j]) ** 0.5) / xi) * (((d[i] - d[j]) ** 2) / (d[i] * d[j])) * ((c[i] * c[j]) ** 0.5)
                y1 += delta_ij * (d[i] + d[j]) / ((d[i] * d[j]) ** 0.5)
                
                sum_k = sum((xi_i[k] / xi) * (((d[i] * d[j]) ** 0.5) / d[k]) for k in elements)
                y2 += delta_ij * sum_k
                
            # Calculate the free energy difference (F - F_id) / k_B*T
            term1 = -1.5 * (1 - y1 + y2 + y3)
            term2 = (3 * y2 + 2 * y3) / (1 - xi)
            term3 = 1.5 * (1 - y1 - y2 - (y3 / 3)) / ((1 - xi) ** 2)
            term4 = (y3 - 1) * math.log(1 - xi)
            f_diff = term1 + term2 + term3 + term4
            
            # Calculate compressibility Z
            z = (1 + xi + (xi ** 2) - 3 * xi * (y1 + y2 * xi) - (xi ** 3) * y3) / ((1 - xi) ** 3)
            
            # Calculate S_E / k_B
            se_kb = f_diff - math.log(z) - (3 - 2 * xi) / ((1 - xi) ** 2) + 3 + math.log((1 + xi + (xi ** 2) - (xi ** 3)) / ((1 - xi) ** 3))
            
            # Scale by Universal Gas Constant (R) to maintain molar units
            return se_kb * self.R

        # Calculate S_E at packing fractions 0.68 (BCC) and 0.74 (FCC) and return the average
        se_068 = calc_se_for_xi(0.68)
        se_074 = calc_se_for_xi(0.74)
        
        return (se_068 + se_074) / 2.0

    def calculate(self, selected_elements, restriction_values):
        try:
            values = dict()
            elements = list(selected_elements.keys())
            
            # PRE-CALCULATION BLOCK
            # Fetching periodic table properties once prevents redundant nested dictionary lookups.
            # Calculating fundamental metrics (radii, fractions, pairs) here centralizes state
            # and guarantees O(N) or O(N^2) complexity instead of recalculating in every model.
            
            props = {el: self.periodic_table[el]["properties"] for el in elements}
            radii = {el: float(props[el]["atomic_radius"]) for el in elements}
            
            # 1. Density
            total_weight = sum(selected_elements[el] * float(props[el]["atomic_weight"]) for el in elements)
            total_volume = sum(selected_elements[el] * float(props[el]["atomic_volume"]) for el in elements)
            values["density"] = total_weight / total_volume if total_volume else 0

            # 2. Delta & Average Radius
            average_atomic_radius = sum(selected_elements[el] * radii[el] for el in elements)
            _delta = sum(selected_elements[el] * (1 - (radii[el] / average_atomic_radius))**2 for el in elements)
            values["delta"] = math.sqrt(_delta) * 100

            # 3. Gamma
            smallest_solid_angle = (1 - math.sqrt((((min(radii.values()) + average_atomic_radius) ** 2) - (average_atomic_radius ** 2)) / ((min(radii.values()) + average_atomic_radius) ** 2)))
            largest_solid_angle = (1 - math.sqrt((((max(radii.values()) + average_atomic_radius) ** 2) - (average_atomic_radius ** 2)) / ((max(radii.values()) + average_atomic_radius) ** 2)))
            values["gamma"] = smallest_solid_angle / largest_solid_angle if largest_solid_angle else 0

            # 4. Standard Properties
            values["vec"] = sum(selected_elements[el] * float(props[el]["nvalence"]) for el in elements)
            values["melting_temp"] = math.ceil(sum(selected_elements[el] * float(props[el]["melting_point"]) for el in elements))
            values["mixing_entropy"] = -self.R * sum(frac * (0 if frac == 0 else math.log(frac)) for frac in selected_elements.values())

            # 5. Centralized pair and enthalpy calculations
            pair_list = list(itertools.combinations(elements, 2))
            mixing_enthalpy = 0
            pair_enthalpy_dict = {} # Caching for models 6, 7, 8
            
            for pair in pair_list:
                h_mix = self.mixing_enthalpy_data.get(pair[0], {}).get(pair[1]) or \
                        self.mixing_enthalpy_data.get(pair[1], {}).get(pair[0], "NaN")
                h_mix_val = float(h_mix) if h_mix != "NaN" else 0.0
                pair_enthalpy_dict[pair] = h_mix_val
                
                pair_frac = selected_elements[pair[0]] * selected_elements[pair[1]]
                mixing_enthalpy += 4 * pair_frac * h_mix_val
                
            values["enthalpy_of_mixing"] = mixing_enthalpy
            values["omega"] = ((values["melting_temp"] * values["mixing_entropy"]) / (abs(values["enthalpy_of_mixing"]) * 1000) if values["enthalpy_of_mixing"] != 0 else 10 ** 10)

            ########## Crystal Str. ##########
            if 2.5 <= values["vec"] <= 3.5:
                values["cstr"] = "HCP"
            elif values["vec"] >= 8.0:
                values["cstr"] = "FCC"
            elif values["vec"] <= 6.87:
                values["cstr"] = "BCC"
            else:
                values["cstr"] = "BCC + FCC"

        except Exception as e:
            raise ValueError(f"Not enough data or calculation error: {e}")

        ############### MODEL 1 ###############
        '''
        X. Yang, Y. Zhang,
        Prediction of high-entropy stabilized solid-solution in multi-component alloys,
        Mater. Chem. Phys. 132 (2012) 233-238. https://doi.org/10.1016/j.matchemphys.2011.11.021.
        '''
        try:
            values["model1"] = "SS" if values["omega"] >= 1.1 and 0 < values["delta"] < 6.6 else "IM"
        except Exception:
            values["model1"] = "N/A"

        ############### MODEL 2 ###############
        '''
        S. Guo, Q. Hu, C. Ng, C.T. Liu,
        More than entropy in high-entropy alloys: Forming solid solutions or amorphous phase,
        Intermetallics 41 (2013) 96-103. https://doi.org/10.1016/j.intermet.2013.05.002.
        '''
        try:
            values["model2"] = "SS" if 0 < values["delta"] < 6.6 and 3.2 > values["enthalpy_of_mixing"] > -11.6 else "IM"
        except Exception:
            values["model2"] = "N/A"

        ############### MODEL 3 ###############
        '''
        Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu,
        Atomic-size effect and solid solubility of multicomponent alloys,
        Scr. Mater. 94 (2015) 28-31. https://doi.org/10.1016/j.scriptamat.2014.09.010.
        '''
        try:
            values["model3"] = "SS" if values["gamma"] < 1.175 and 3.2 > values["enthalpy_of_mixing"] > -11.6 else "IM"
        except Exception:
            values["model3"] = "N/A"

        ############### MODEL 4 ###############
        '''
        A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam,
        A geometrical parameter for the formation of disordered solid solutions in multi-component alloys,
        Intermetallics 53 (2014) 112-119. https://doi.org/10.1016/j.intermet.2014.04.019.
        '''
        try:
            _lambda = values["mixing_entropy"] / (values["delta"] ** 2) if values["delta"] != 0 else float('inf')
            values["lambda"] = _lambda
            
            h_mix = values["enthalpy_of_mixing"]
            if _lambda < 0.24 and h_mix < -15:
                values["model4"] = "IM"
            elif 0.24 <= _lambda <= 0.96 and -15 <= h_mix <= -5:
                values["model4"] = "SS+IM"
            elif 0.96 <= _lambda and -5 <= h_mix <= 0:
                values["model4"] = "SS"
            elif 0.96 <= _lambda and 0 < h_mix:
                values["model4"] = "SS+SS"
            else:
                if _lambda < 0.24:
                    values["model4"] = "[IM]"
                elif 0.96 < _lambda:
                    values["model4"] = "[SS]"
                else:
                    values["model4"] = "[Mixed]"
        except Exception:
            values["model4"] = "N/A"
            values["lambda"] = "N/A"

        ############### MODEL 5 ###############
        '''
        M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks,
        Criteria for Predicting the Formation of Single-Phase High-Entropy Alloys,
        Phys. Rev. X 5 (2015) 011041. https://doi.org/10.1103/PhysRevX.5.011041.
        '''
        try:
            delta_Hf_alloy = []
            for pair in pair_list:
                if pair[0] in self.fusion_enthalpy_data and pair[1] in self.fusion_enthalpy_data[pair[0]]:
                    delta_Hf_alloy.append(self.fusion_enthalpy_data[pair[0]][pair[1]])

            if delta_Hf_alloy:
                annealing_temperature = values["melting_temp"] * 0.55
                threshold = -1 * annealing_temperature * values["mixing_entropy"] * 1.04 * (10 ** -2)
                values["model5"] = "SS" if threshold <= min(delta_Hf_alloy) <= 37 else "IM"
            else:
                values["model5"] = "N/A"
        except Exception:
            values["model5"] = "N/A"

        ############### MODEL 6 ###############
        '''
        O.N. Senkov, D.B. Miracle,
        A new thermodynamic parameter to predict formation of solid solution or intermetallic phases in high entropy alloys,
        J. Alloys Compd. 658 (2016) 603-607. https://doi.org/10.1016/j.jallcom.2015.10.279.
        '''
        try:
            delta_Hf_IM = []
            for pair in pair_list:
                if pair[0] in self.fusion_enthalpy_data and pair[1] in self.fusion_enthalpy_data[pair[0]]:
                    pair_fraction = selected_elements[pair[0]] * selected_elements[pair[1]]
                    delta_Hf_IM.append(self.fusion_enthalpy_data[pair[0]][pair[1]] * pair_fraction)

            delta_H_IM = 4 * sum(delta_Hf_IM) * 0.09648

            K2 = 0.6
            T_an = values["melting_temp"] * 0.6
            omega_T = ((T_an * values["mixing_entropy"]) / (abs(values["enthalpy_of_mixing"]) * 1000) if values["enthalpy_of_mixing"] != 0 else 10 ** 10)
            K1_cr_T = (omega_T * (1 - K2)) + 1
            
            ratio = (delta_H_IM / values["enthalpy_of_mixing"]) if values["enthalpy_of_mixing"] != 0 else 10 ** 10
            
            values["model6"] = f"SS (Tₐₙ: {T_an:.1f} K)" if K1_cr_T > ratio else f"IM  (Tₐₙ: {T_an:.1f} K)"
        except Exception:
            values["model6"] = "N/A"
            
        ############### MODEL 7 ###############
        '''
        Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang,
        Design of high entropy alloys: A single-parameter thermodynamic rule, 
        Scripta Materialia 104 (2015) 53-55. https://doi.org/10.1016/j.scriptamat.2015.03.023.
        '''
        try:
            s_c = values["mixing_entropy"]
            s_h = (abs(values["enthalpy_of_mixing"]) * 1000) / values["melting_temp"]
            s_e = self._excess_entropy_of_mixing(selected_elements, radii) 
            
            phi_m7 = (s_c - s_h) / abs(s_e) if s_e != 0 else float('inf')
            
            values["model7"] = "SS" if phi_m7 >= 20 else "IM"
            values["phi_model7"] = phi_m7
        except Exception:
            values["model7"] = "N/A"
            values["phi_model7"] = "N/A"

        ############### MODEL 8 ###############
        '''
        D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie,
        Predicting the formation and stability of single phase high-entropy alloys,
        Acta Materialia 104 (2016) 172-179. https://doi.org/10.1016/j.actamat.2015.11.040.
        Supplementary Material: Miedema's macroscopic atom model direct max-magnitude application.
        '''
        try:
            # Calculate Gibbs Free Energy of the Solid Solution (G_ss = H_mix - T * S_mix)
            # Multiplying enthalpy by 1000 to convert kJ/mol to J/mol
            delta_h_ss = values["enthalpy_of_mixing"] * 1000 
            delta_s_conf = values["mixing_entropy"]
            t_m = values["melting_temp"]
            
            delta_g_ss = delta_h_ss - (t_m * delta_s_conf)

            # Retrieve only valid mixing enthalpies computed previously
            pair_enthalpies = [val for val in pair_enthalpy_dict.values() if val != 0.0]
            
            if pair_enthalpies:
                # Find the binary pair with the largest magnitude (most negative) enthalpy of mixing.
                # Converts kJ/mol to J/mol.
                min_binary_enthalpy = min(pair_enthalpies) * 1000
                
                # Based on the supplementary equations (S9, S10), the largest magnitude binary 
                # enthalpy is taken directly as delta_G_int without stoichiometric multiplier.
                delta_g_max = min_binary_enthalpy
                
                phi_m8 = delta_g_ss / -abs(delta_g_max) if delta_g_max != 0 else float('inf')
                
                values["model8"] = "SS" if phi_m8 >= 1.0 else "IM"
                values["phi_model8"] = phi_m8
            else:
                values["model8"] = "N/A"
                values["phi_model8"] = "N/A"
                
        except Exception:
            values["model8"] = "N/A"
            values["phi_model8"] = "N/A"

        # Check Criteria Validation
        meets_criteria = True
        if restriction_values:
            for prop, restriction in restriction_values.items():
                if prop not in values:
                    continue
                if isinstance(restriction, dict):
                    min_value = float(restriction.get('min', float('-inf')))
                    max_value = float(restriction.get('max', float('inf')))
                    if not (min_value <= float(values[prop]) <= max_value):
                        meets_criteria = False
                        break
                else:
                    if restriction != values[prop]:
                        meets_criteria = False
                        break
        
        return values, meets_criteria

    def get_atomic_weight(self, element: str) -> float:
        return self.periodic_table[element]["properties"]["atomic_weight"]