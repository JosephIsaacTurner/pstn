import argparse
import os
import sys
import re
import numpy as np
import nibabel as nib
from nilearn.maskers import NiftiMasker
from .datasets import Dataset
from .preprocessing import load_data, is_nifti_like
from .permutation_inference import permutation_analysis, permutation_analysis_nifti

NON_IMPLEMENTED_ARGS = [
    "-s",
    "-npcmethod",
    "-npcmod",
    "-npccon",
    "-npc",
    "-mv",
    "-C",
    "-Cstat",
    "-tfce1D",
    "-tfce2D",
    "-corrmod",
    "-concordant",
    "-reversemasks",
    "-quiet",
    "-advanced",
    "-con",
    "-tonly",
    "-cmcp",
    "-cmcx",
    "-conskipcount",
    "-Cuni",
    "-Cnpc",
    "-Cmv",
    "-designperinput",
    "-ev4vg",
    "-evperdat",
    "-inormal",
    "-probit",
    "-inputmv",
    "-noranktest",
    "-noniiclass",
    "-nounivariate",
    "-nouncorrected",
    "-pmethodp",
    "-pmethodr",
    "-removevgbysize",
    "-rmethod",
    "-savedof",
    "-savemask",
    "-savemetrics",
    "-saveparametric",
    "-saveglm",
    "-syncperms",
    "-subjidx",
    "-tfce_H",
    "tfce_E",
    "tfce_dh",
    "-Tuni",
    "-Tnpc",
    "-Tmv",
    "-transposedata",
    "-verbosefilenames",
    "-vgdemean",
]


def setup_parser():
    """Set up the argument parser for prism command."""
    parser = argparse.ArgumentParser(
        description="PALM (Permutation Analysis of Linear Models) for Python",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Required arguments
    required = parser.add_argument_group("required arguments")
    required.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input file (.nii.gz, .nii, .csv, .npy, .txt)",
    )
    required.add_argument(
        "-d", "--design", required=True, help="Design matrix file (.csv or .npy)"
    )
    required.add_argument(
        "-t", "--contrast", required=True, help="Contrast file (.csv or .npy)"
    )
    parser.add_argument(
        "-f",
        "--f_contrast_indices",
        type=str,
        default=None,
        help="File identifying the indices of the contrasts to be used for F-test (.csv or .npy)",
    )
    parser.add_argument(
        "-fonly",
        "--f_only",
        action="store_true",
        default=False,
        help="Perform F-test only",
    )
    parser.add_argument(
        "-o", "--output", default="palm", help="Output prefix for all saved files"
    )
    # Optional arguments
    parser.add_argument("-m", "--mask", help="Mask image file (.nii or .nii.gz)")
    parser.add_argument(
        "-n",
        "--n_permutations",
        type=int,
        default=1000,
        help="Number of permutations to perform",
    )
    parser.add_argument(
        "-eb",
        "--exchangeability_matrix",
        help="Exchangeability blocks file (.csv or .npy)",
    )
    parser.add_argument(
        "-vg",
        "--variance_groups",
        type=str,
        default=None,
        help='Variance groups file (.csv, .npy) or "auto" for automatic detection',
    )
    parser.add_argument(
        "-within",
        action="store_true",
        default=None,
        help="If True, exchangeability blocks are within-subjects",
    )
    parser.add_argument(
        "-whole",
        action="store_true",
        default=False,
        help="If True, exchangeability blocks are whole-brain",
    )
    parser.add_argument(
        "-ee",
        "--permute_design",
        action="store_true",
        default=True,
        help="Assume exchangeability errors, to allow permutations",
    )
    parser.add_argument(
        "-ise",
        "--flip_signs",
        action="store_true",
        default=False,
        help="Assume independent and symmetric errors (ISE), to allow sign flipping",
    )
    parser.add_argument(
        "-T", "--tfce", action="store_true", default=False, help="Enable TFCE inference"
    )
    parser.add_argument(
        "-fdr",
        "--fdr",
        action="store_true",
        default=True,
        help="Produce FDR-adjusted p-values",
    )
    parser.add_argument(
        "-save1-p",
        "--save1_p",
        action="store_true",
        default=False,
        help="Save (1-p) instead of actual p values (default if no format specified)",
    )
    parser.add_argument(
        "-logp",
        "--logp",
        action="store_true",
        default=False,
        help="Save -log10(p) instead of actual p values",
    )
    parser.add_argument(
        "-twotail",
        "--two-tailed",
        action="store_true",
        default=False,
        help="Do two-tailed voxelwise tests",
    )
    parser.add_argument(
        "-accel",
        "--accel",
        nargs="?",
        const=True,
        default=False,
        help='Enable acceleration. Can accept "tail" as a value',
    )
    parser.add_argument(
        "-corrcon",
        "--correct_across_contrasts",
        action="store_true",
        default=False,
        help="Use FWE correction across contrasts",
    )
    parser.add_argument(
        "-pearson",
        "--pearson_r",
        action="store_true",
        default=False,
        help="Use Pearson r instead of t-statistic",
    )
    parser.add_argument(
        "-demean",
        "--demean",
        action="store_true",
        default=False,
        help="Demean the data before analysis",
    )
    parser.add_argument(
        "-saveperms",
        "--save_permutations",
        action="store_true",
        default=False,
        help="Save one statistic image per permutation",
    )
    parser.add_argument(
        "-seed",
        "--random_state",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "-zstat",
        "--zstat",
        action="store_true",
        default=False,
        help="Save z-statistics instead of t-statistics",
    )

    for arg in NON_IMPLEMENTED_ARGS:
        parser.add_argument(
            arg,
            action="store_true",
            default=False,
            help=f"Argument {arg} is not yet implemented in prism",
        )

    return parser


def validate_args(args):
    """Validate the parsed arguments."""
    # Check that input file exists and has valid extension
    if not os.path.exists(args.input):
        sys.exit(f"Error: Input file '{args.input}' does not exist")

    valid_input_extensions = [".nii.gz", ".nii", ".csv", ".npy", ".txt"]
    if not any(args.input.endswith(ext) for ext in valid_input_extensions):
        sys.exit(
            f"Error: Input file must be one of: {', '.join(valid_input_extensions)}"
        )

    # Check mask file if provided
    if args.mask:
        if not os.path.exists(args.mask):
            sys.exit(f"Error: Mask file '{args.mask}' does not exist")

        if not (args.mask.endswith(".nii") or args.mask.endswith(".nii.gz")):
            sys.exit("Error: Mask file must be .nii or .nii.gz format")

    # Check design and contrast files
    for file_arg, arg_name in [
        (args.design, "Design matrix"),
        (args.contrast, "Contrast"),
    ]:
        if not os.path.exists(file_arg):
            sys.exit(f"Error: {arg_name} file '{file_arg}' does not exist")

        if not (file_arg.endswith(".csv") or file_arg.endswith(".npy")):
            sys.exit(f"Error: {arg_name} file must be .csv or .npy format")

    # Check f_contrast_indices file if provided
    if args.f_contrast_indices:
        if not os.path.exists(args.f_contrast_indices):
            sys.exit(
                f"Error: F-contrast indices file '{args.f_contrast_indices}' does not exist"
            )

        if not (
            args.f_contrast_indices.endswith(".csv")
            or args.f_contrast_indices.endswith(".npy")
        ):
            sys.exit("Error: F-contrast indices file must be .csv or .npy format")

    # Check exchangeability blocks file if provided
    if args.exchangeability_matrix and not os.path.exists(args.exchangeability_matrix):
        sys.exit(
            f"Error: Exchangeability blocks file '{args.exchangeability_matrix}' does not exist"
        )

    # Handle variance groups. Can be either None, a path to a csv/npy, or "auto". If a file, let's load it.
    if args.variance_groups is not None:
        if args.variance_groups.lower() == "auto":
            pass
        elif not os.path.exists(args.variance_groups):
            sys.exit(
                f"Error: Variance groups file '{args.variance_groups}' does not exist"
            )
        else:
            if not (
                args.variance_groups.endswith(".csv")
                or args.variance_groups.endswith(".npy")
            ):
                sys.exit("Error: Variance groups file must be .csv or .npy format")

    # Handle accel parameter
    if isinstance(args.accel, str):
        if args.accel.lower() == "tail":
            args.accel = True
        else:
            print(
                f'Warning: accel method "{args.accel}" not recognized. Using "tail" instead. (GPD approximation)'
            )
            args.accel = True
    elif args.accel is True:
        print("Acceleration enabled with default method: tail")

    # Handle within and whole parameters.
    if args.within is None and args.whole is True:
        args.within = False
    elif args.within is None:
        args.within = True

    # Handle p-value format options
    if args.save1_p is True and args.logp is True:
        # Both were explicitly specified -- but let's not let the user do that.
        # We'll print a warning and set logp to be False and keep 1_p to be True
        print("Warning: Both -save1-p and -logp were specified. Using -save1-p.")
        args.logp = False

    for arg in NON_IMPLEMENTED_ARGS:
        if getattr(args, arg[1:], False):
            print(
                f"Warning: Argument {arg} is not yet implemented in prism. Ignoring it."
            )
            print(
                "Please open an issue on GitHub if you need this feature, or use the original PALM."
            )

    return args


def get_output_path(output_arg):
    # Case 1: It's a directory that exists
    if os.path.isdir(output_arg):
        return os.path.join(output_arg, "")  # Return with trailing slash

    # Case 2: It contains a directory path
    dirname = os.path.dirname(output_arg)
    if dirname:
        # Check if the path is absolute
        if os.path.isabs(dirname):
            # Use the absolute path as is
            os.makedirs(dirname, exist_ok=True)
            return output_arg
        else:
            # Relative path - prepend current working directory
            full_dirname = os.path.join(os.getcwd(), dirname)
            os.makedirs(full_dirname, exist_ok=True)
            return os.path.join(os.getcwd(), output_arg)

    # Case 3: Just a prefix with no directory part
    return os.path.join(os.getcwd(), output_arg)


def main():
    parser = setup_parser()
    args, unknown = parser.parse_known_args()
    args = validate_args(args)

    # Warn about unrecognized args
    if unknown:
        print("\nWarning: The following arguments are not yet implemented in prism:")
        for arg in unknown:
            print(f"  {arg}")
        print(
            "\nThese may be available in the original PALM distribution by Anderson Winkler."
        )
        print(
            "If your analysis requires these features, consider using the original PALM for now.\n"
        )

    # Print parsed arguments for testing
    print("PRISM - PeRmutation Inference for Statistical Mapping")
    print("=============================================")
    print(f"Input file: {args.input}")
    print(f"Design matrix: {args.design}")
    print(f"Contrast: {args.contrast}")
    print(f"Number of permutations: {args.n_permutations}")
    print(f"Output prefix: {args.output}")


    output_prefix = get_output_path(args.output)

    stat_function = "auto" if not args.pearson_r else "pearson"
    f_stat_function = "auto" if not args.pearson_r else "pearson"

    dataset = Dataset(
        data=args.input,
        design=args.design,
        contrast=args.contrast,
        output_prefix=output_prefix,
        f_contrast_indices=args.f_contrast_indices,
        two_tailed=args.two_tailed,
        exchangeability_matrix=args.exchangeability_matrix,
        vg_auto=True if args.variance_groups == "auto" else False,
        variance_groups=args.variance_groups if args.variance_groups != "auto" else None,
        within=args.within,
        whole=args.whole,
        flip_signs=args.flip_signs,
        stat_function=stat_function,
        f_stat_function=f_stat_function,
        f_only=args.f_only,
        n_permutations=args.n_permutations,
        accel_tail=args.accel,
        save_1minusp=args.save1_p,
        save_neglog10p=args.logp,
        correct_across_contrasts=args.correct_across_contrasts,
        random_state=args.random_state,
        demean=args.demean,
        zstat=args.zstat,
        save_permutations=args.save_permutations,
        mask_img=args.mask,
        tfce=args.tfce
    )
    dataset.save_config()

    results = dataset.permutation_analysis()

    print("Analysis complete. Results saved to output files.")

    # # --- Commenting out on Apr. 30th, 2025, as we intent all processing to be handled in the Dataset class.
    # # Continue with the actual processing...
    # # Your PALM implementation code would go here
    # data = load_data(args.input)
    # design = load_data(args.design)
    # contrast = load_data(args.contrast)

    # if args.f_contrast_indices:
    #     f_contrast_indices = load_data(args.f_contrast_indices)
    #     print(f"F-contrast indices: {f_contrast_indices}")
    # else:
    #     f_contrast_indices = None

    # input_is_nifti_like = is_nifti_like(data)

    # if input_is_nifti_like:
    #     print("Input data is NIfTI-like. Using volumetric dense analysis.")
    #     # Verify that we got a mask img
    #     if args.mask is None:
    #         print(
    #             "Warning: Mask image not provided. We'll try to move forward, but behavior may be unpredictable."
    #         )

    #     results = permutation_analysis_nifti(
    #         imgs=data,
    #         mask_img=args.mask,
    #         design=design,
    #         contrast=contrast,
    #         stat_function=stat_function,
    #         n_permutations=args.n_permutations,
    #         random_state=args.random_state,
    #         two_tailed=args.two_tailed,
    #         exchangeability_matrix=(
    #             load_data(args.exchangeability_matrix)
    #             if args.exchangeability_matrix
    #             else None
    #         ),
    #         vg_auto=True if args.variance_groups == "auto" else False,
    #         variance_groups=(
    #             load_data(args.variance_groups)
    #             if (args.variance_groups is not None and args.variance_groups != "auto")
    #             else None
    #         ),
    #         within=args.within,
    #         whole=args.whole,
    #         flip_signs=args.flip_signs,
    #         accel_tail=args.accel,
    #         demean=args.demean,
    #         f_stat_function=f_stat_function,
    #         f_contrast_indices=f_contrast_indices,
    #         f_only=args.f_only,
    #         correct_across_contrasts=args.correct_across_contrasts,
    #         tfce=args.tfce,
    #         save_1minusp=args.save1_p,
    #         save_neglog10p=args.logp,
    #         zstat=args.zstat,
    #         output_prefix=output_prefix,
    #         save_permutations=args.save_permutations,
    #     )

    # else:
    #     results = permutation_analysis(
    #         data=data,
    #         design=design,
    #         contrast=contrast,
    #         stat_function=stat_function,
    #         n_permutations=args.n_permutations,
    #         random_state=args.random_state,
    #         two_tailed=args.two_tailed,
    #         exchangeability_matrix=(
    #             load_data(args.exchangeability_matrix)
    #             if args.exchangeability_matrix
    #             else None
    #         ),
    #         vg_auto=True if args.variance_groups == "auto" else False,
    #         variance_groups=(
    #             load_data(args.variance_groups)
    #             if (args.variance_groups is not None and args.variance_groups != "auto")
    #             else None
    #         ),
    #         within=args.within,
    #         whole=args.whole,
    #         flip_signs=args.flip_signs,
    #         accel_tail=args.accel,
    #         demean=args.demean,
    #         f_stat_function=f_stat_function,
    #         f_contrast_indices=f_contrast_indices,
    #         f_only=args.f_only,
    #         correct_across_contrasts=args.correct_across_contrasts,
    #         save_1minusp=args.save1_p,
    #         save_neglog10p=args.logp,
    #         zstat=args.zstat,
    #         output_prefix=output_prefix,
    #         save_permutations=args.save_permutations,
    #     )

if __name__ == "__main__":
    main()
