import streamlit as st
import numpy as np
import importlib
import pychell.utils as pcutils
import plotly

def make_title(title):
    return st.title(title)

class StreamlitComponent:
    
    def __init__(self, comps, label="", *args, **kwargs):
        self.comps = comps
        self.label = label
        
    def write(self, *args, **kwargs):
        pass

class DataSelector(StreamlitComponent):
    
    def __init__(self, comps, data):
        super().__init__(comps=comps, label="Data Selector")
        self.data = data
        self.write()
        
    def write(self):
        # Use or ignore any instruments as st checkboxes.
        st.markdown("## Data")
        for data in self.data.values():
            self.comps["use_" + data.label] = st.checkbox(label=data.label + " [" + str(len(data.t)) + "]", value=True)
        self.update_data()
        return self.comps
    
    def update_data(self):
        for inst in list(self.data.keys()):
            if not self.comps["use_" + inst]:
                del self.data[inst]
    
class RVActions(StreamlitComponent):
    
    def __init__(self, comps, optprob):
        super().__init__(comps=comps, label="Data Selector")
        self.optprob = optprob
        self.write()
        
    def write(self):
        
        # Primary actions
        st.markdown('## Actions')
        self.comps["max_like_button"] = st.button(label='Max Like')
        self.comps["sample_button"] = st.button(label='MCMC')
        self.comps["model_comp_button"] = st.button(label='Model Comparison')
        self.comps["per_search_button"] = st.button('Period Search')
        self.comps["use_gp_input"] = st.checkbox(label="Use GP", value=True)
        
        # Period search options
        st.markdown('## Period Search Options:')
        st.markdown('### Periodogram Type:')
        self.comps["persearch_kind_input"] = st.radio(label="", options=["GLS", "Brute Force"])
        self.comps["persearch_remove"] = {}
        st.markdown('### Remove Planets:')
        remove_planets_pgram = []
        for planet_index in self.optprob.planets_dict:
            self.comps["persearch_remove"][planet_index] = st.checkbox(label=str(planet_index))
            if self.comps["persearch_remove"][planet_index]:
                remove_planets_pgram.append(planet_index)
    
        self.comps["remove_planet_inputs"] = remove_planets_pgram
        pgcols = st.beta_columns(2)
        self.comps["persearch_min_input"] = pgcols[0].text_input(label='Period min', value=1.1)
        self.comps["persearch_max_input"] = pgcols[1].text_input(label='Period max', value=100)
        return self.comps
    
class MaxLikeResult(StreamlitComponent):
    
    def __init__(self, comps, optprob, opt_result):
        super().__init__(comps=comps, label="Optimize Result")
        self.optprob = optprob
        self.opt_result = opt_result
        self.write()
        
    def write(self):
    
        # Display Results
        st.markdown('# Optimize Results')
        st.text(repr(self.opt_result['pbest']))
        st.markdown('## Function calls: ' + str(self.opt_result['fcalls']))
        st.markdown('## ln(L): ' + str(-1 * self.opt_result['fbest']))
    
        # Full RV plot
        st.markdown('## Full RV Plot')
        plotly_fig = self.optprob.rv_plot(opt_result=self.opt_result, n_model_pts=5000)
        self.comps["rvfigfull_maxlike"] = st.plotly_chart(plotly_fig)
    
        # Phased rv plot
        st.markdown('## Phased Planets')
        for planet_index in self.optprob.planets_dict:
            name = "figplanet_" + str(planet_index) + "_maxlike"
            plotly_fig = self.optprob.rv_phase_plot(planet_index=planet_index, opt_result=self.opt_result)
            self.comps[name] = st.plotly_chart(plotly_fig)
            
        return self.comps
    
class ModelCompResult(StreamlitComponent):
    
    def __init__(self, comps, optprob, mc_result):
        super().__init__(comps=comps, label="Optimize Result")
        self.optprob = optprob
        self.mc_result = mc_result
        self.write()
        
    def write(self):
        st.markdown('# Model Comparison')
        for i in range(len(self.mc_result)):
            self.comps["mc_result_" + str(i+1)] = st.write(self.mc_result[i])
        return self.comps
    
class MCMCResult(StreamlitComponent):
    
    def __init__(self, comps, optprob, sampler_result):
        super().__init__(comps=comps, label="Optimize Result")
        self.optprob = optprob
        self.sampler_result = sampler_result
        self.write()
        
    def write(self):
    
        # Display Results
        st.markdown('# MCMC Results')
        st.text(repr(self.sampler_result['pbest']))
        st.text('Parameter Uncertainties: ')
        st.text(self.sampler_result['punc'])
        st.markdown('## ln(L): ' + str(self.sampler_result['lnL']))
    
        # Full RV plot
        st.markdown('## Full RV Plot')
        plotly_fig = self.optprob.rv_plot(opt_result=self.sampler_result, n_model_pts=5000)
        self.comps["rvfigfull_mcmc"] = st.plotly_chart(plotly_fig)
    
        # Phased rv plot
        st.markdown('## Phased Planets')
        for planet_index in self.optprob.planets_dict:
            name = "figplanet_" + str(planet_index) + "_mcmc"
            plotly_fig = self.optprob.rv_phase_plot(planet_index=planet_index, opt_result=self.sampler_result)
            self.comps[name] = st.plotly_chart(plotly_fig)
    
        # Corner plot
        st.markdown('## Corner Plot')
        corner_plot = self.optprob.corner_plot(sampler_result=self.sampler_result)
        self.comps["corner_plot"] = st.pyplot(corner_plot)
      
class GLSResult(StreamlitComponent):
    
    def __init__(self, comps, optprob, gls_result=None):
        super().__init__(comps=comps, label="Period Search Result")
        self.optprob = optprob
        self.gls_result = gls_result
        self.write()
        
    def write(self):
        fig = plotly.subplots.make_subplots(rows=1, cols=1)
        fig.add_trace(plotly.graph_objects.Scatter(x=1 / self.gls_result.f, y=self.gls_result.power, line=dict(color='black', width=1), showlegend=False), row=1, col=1)
        fig.update_xaxes(title_text='<b>Period [days]</b>', row=1, col=1)
        fig.update_yaxes(title_text='<b>Power</b>', row=1, col=1)
        fig.update_layout(template="ggplot2")
        fig.update_xaxes(tickprefix="<b>",ticksuffix ="</b><br>")
        fig.update_yaxes(tickprefix="<b>",ticksuffix ="</b><br>")
        st.plotly_chart(fig)
        fig.write_html(self.optprob.output_path + self.optprob.star_name.replace(' ', '_') + '_glspgram_' + pcutils.gendatestr(time=True) + '.html')
        
        
class RVPeriodSearchResult(StreamlitComponent):
        
    def __init__(self, comps, optprob, periods, persearch_result=None):
        super().__init__(comps=comps, label="Period Search Result")
        self.optprob = optprob
        self.periods = periods
        self.persearch_result = persearch_result
        self.write()
    
    def write(self):
        
        # Extract log L
        lnLs = np.array([-1 * result["fbest"] for result in self.persearch_result])
        
        # Create a plot and return results
        fig = plotly.subplots.make_subplots(rows=1, cols=1)
        fig.add_trace(plotly.graph_objects.Scatter(x=self.periods, y=lnLs, line=dict(color='black', width=1)), row=1, col=1)
        fig.update_xaxes(title_text='Period [days]', row=1, col=1)
        fig.update_yaxes(title_text='ln(L)', row=1, col=1)
        fig.update_xaxes(tickprefix="<b>",ticksuffix ="</b><br>")
        fig.update_yaxes(tickprefix="<b>",ticksuffix ="</b><br>")
        st.plotly_chart(fig)
        fig.write_html(self.optprob.output_path + self.optprob.star_name.replace(' ', '_') + '_brute_force_pgram_' + pcutils.gendatestr(time=True) + '.html')