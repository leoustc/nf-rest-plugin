
conda config --add channels bioconda
conda config --add channels conda-forge
conda config --set channel_priority strict

conda create --name nf-gradle-env nextflow gradle oci-cli
conda activate nf-gradle-env


# install terraform
conda install conda-forge::terraform
conda install oci-cli