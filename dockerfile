# 1. Start from our working "Frankenstein" base (ROCm 6.2 + Driver 6.1)
FROM rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_release_2.3.0

USER root
ARG DEBIAN_FRONTEND=noninteractive

# 2. (Existing Step) Install the AMD "Bridge" Drivers for WSL
RUN apt-get update && apt-get install -y wget && \
    wget https://repo.radeon.com/amdgpu-install/6.1.3/ubuntu/jammy/amdgpu-install_6.1.60103-1_all.deb && \
    apt-get install -y -o Dpkg::Options::="--force-confnew" ./amdgpu-install_6.1.60103-1_all.deb && \
    rm amdgpu-install_6.1.60103-1_all.deb && \
    amdgpu-install -y --usecase=wsl --no-dkms --accept-eula

# 3. (NEW) Install R and System Dependencies
# We add software-properties-common to manage repositories
RUN apt-get update && apt-get install -y \
    software-properties-common \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    r-base \
    r-base-dev

# 4. (NEW) Install Essential R Packages
# We install 'reticulate' (to talk to Python/GPU) and 'tidyverse' (for sanity)
RUN R -e "install.packages(c('reticulate', 'tidyverse', 'rvest', 'httr2', 'jsonlite'), repos='https://cloud.r-project.org/')"

# 5. (NEW) Install Python Scraping/Data Libraries
# These sit alongside the pre-installed PyTorch
RUN pip3 install --no-cache-dir \
    pandas \
    numpy \
    scipy \
    beautifulsoup4 \
    selenium \
    playwright \
    lxml

# 6. Cleanup and Config
RUN apt-get clean && rm -rf /var/lib/apt/lists/*
ENV HSA_OVERRIDE_GFX_VERSION=11.0.0
ENV HSA_ENABLE_SDMA=0

WORKDIR /app
CMD ["sleep", "infinity"]