#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# python survey_sim.py name fconfig twilight 

#######################################################################
# master branch desi_surveysim 
#######################################################################
#source activate desi_surveysim
# default
#python $DIR/survey_sim.py default config_default.yaml False
#python $DIR/survey_sim.py default config_default.yaml True
# 150s 
#python $DIR/survey_sim.py 150s config_150s.yaml False
#python $DIR/survey_sim.py 150s config_150s.yaml True
#conda deactivate 

#######################################################################
# forked branch desi_surveysim_branch
#######################################################################
source activate desi_surveysim_branch
# default
#python $DIR/survey_sim.py default config_default.yaml False
#python $DIR/survey_sim.py default config_default.yaml True
# 150s 
#python $DIR/survey_sim.py 150s_skybranch config_150s.yaml False True
python $DIR/survey_sim.py 150s_skybranch config_150s.yaml True True

conda deactivate 
