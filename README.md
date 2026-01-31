## Depth Pro: Sharp Monocular Metric Depth for Videos

# Getting Started

We recommend setting up a virtual environment. Using e.g. miniconda, the `depth_pro` package can be installed via:

```bash
conda create -n depth-pro-for-video -y python=3.9
conda activate depth-pro-for-video

pip install -e .
```

To download pretrained checkpoints follow the code snippet below:
```bash
source get_pretrained_models.sh   # Files will be downloaded to `checkpoints` directory.
```

### Running from commandline

We provide a helper script to directly run the model on a single image:
```bash
# Run prediction on a single image:
depth-pro-run -i ./data/example.jpg -o ./data/depth/ --skip-display
# Run `depth-pro-run -h` for available options.
```

## License
This sample code is released under the [LICENSE](LICENSE) terms.

The model weights are released under the [LICENSE](LICENSE) terms.

## Acknowledgements

Our codebase is built using multiple opensource contributions, please see [Acknowledgements](ACKNOWLEDGEMENTS.md) for more details.

Please check the paper for a complete list of references and datasets used in this work.
