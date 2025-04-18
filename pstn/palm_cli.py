import argparse
import os
import sys
import re
import numpy as np
import nibabel as nib
from nilearn.maskers import NiftiMasker
from .loading import load_data, is_nifti_like
from .inference import permutation_analysis, permutation_analysis_volumetric_dense, SavePermutationManager
from .stats import pearson_r, r_squared

# TODO:
# Implement other statistical methods beyond t-test
# Implement vgdemean
# As of Friday, April 17th, 2025
NON_IMPLEMENTED_ARGS = [
    '-s', '-npcmethod', '-npcmod', '-npccon', '-npc',
    '-mv', '-C', '-Cstat', '-tfce1D', '-tfce2D', '-corrmod',
    '-concordant', '-reversemasks', '-quiet', '-advanced', 
    '-con', '-tonly', '-cmcp', '-cmcx', '-conskipcount', '-Cuni', '-Cnpc', 
    '-Cmv', '-designperinput', '-ev4vg', '-evperdat', '-inormal', '-probit', 
    '-inputmv', '-noranktest', '-noniiclass', '-nounivariate', '-nouncorrected',
    '-pmethodp', '-pmethodr', '-removevgbysize', '-rmethod', '-savedof', 
    '-savemask', '-savemetrics', '-saveparametric', '-saveglm', '-syncperms',
    '-subjidx', '-tfce_H', 'tfce_E', 'tfce_dh', '-Tuni', '-Tnpc', '-Tmv',
    '-transposedata', '-verbosefilenames', '-vgdemean', '-zstat'
]

def setup_parser():
    """Set up the argument parser for pypalm command."""
    parser = argparse.ArgumentParser(
        description='PALM (Permutation Analysis of Linear Models) for Python',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Required arguments
    required = parser.add_argument_group('required arguments')
    required.add_argument('-i', '--input', required=True,
                        help='Input file (.nii.gz, .nii, .csv, .npy, .txt)')
    required.add_argument('-d', '--design', required=True,
                        help='Design matrix file (.csv or .npy)')
    required.add_argument('-t', '--contrast', required=True,
                        help='Contrast file (.csv or .npy)')
    parser.add_argument('-f', '--f_contrast_indices', type=str, default=None,
                        help='File identifying the indices of the contrasts to be used for F-test (.csv or .npy)')
    parser.add_argument('-fonly', "--f_only", action='store_true', default=False,
                        help='Perform F-test only')
    parser.add_argument('-o', '--output', default='palm',
                    help='Output prefix for all saved files')
    # Optional arguments
    parser.add_argument('-m', '--mask', 
                        help='Mask image file (.nii or .nii.gz)')
    parser.add_argument('-n', '--n_permutations', type=int, default=1000,
                        help='Number of permutations to perform')
    parser.add_argument('-eb', '--exchangeability_blocks', 
                        help='Exchangeability blocks file (.csv or .npy)')
    parser.add_argument('-vg', '--variance_groups', type=str, default=None,
                        help='Variance groups file (.csv, .npy) or "auto" for automatic detection')
    parser.add_argument('-within', action='store_true', default=True,
                        help='If True, exchangeability blocks are within-subjects')
    parser.add_argument('-whole', action='store_true', default=False,
                        help='If True, exchangeability blocks are whole-brain')
    parser.add_argument('-ee', '--permute_design', action='store_true', default=True,
                        help='Assume exchangeability errors, to allow permutations')
    parser.add_argument('-ise', '--flip_signs', action='store_true', default=False,
                        help='Assume independent and symmetric errors (ISE), to allow sign flipping')
    parser.add_argument('-T', '--tfce', action='store_true', default=False,
                        help='Enable TFCE inference')
    parser.add_argument('-fdr', "--fdr", action='store_true', default=True,
                        help='Produce FDR-adjusted p-values')
    parser.add_argument('-save1-p', "--save1-p", action='store_true', default=None,
                    help='Save (1-p) instead of actual p values (default if no format specified)')
    parser.add_argument('-logp', "--logp", action='store_true', default=False,
                    help='Save -log10(p) instead of actual p values')
    parser.add_argument('-twotail', "--two-tailed", action='store_true', default=True,
                        help='Do two-tailed voxelwise tests')
    parser.add_argument('-accel', "--accel", nargs='?', const=True, default=False,
                        help='Enable acceleration. Can accept "tail" as a value')
    parser.add_argument('-corrcon', "--correct_across_contrasts", action='store_true', default=False,
                        help='Use FWE correction across contrasts')
    parser.add_argument('-pearson', "--pearson_r", action='store_true', default=False,
                        help='Use Pearson r instead of t-statistic')
    parser.add_argument('-demean', "--demean", action='store_true', default=False,
                        help='Demean the data before analysis')
    parser.add_argument('-saveperms', "--save_permutations", action='store_true', default=False,
                        help='Save one statistic image per permutation')
    parser.add_argument('-seed', '--random_state', type=int, default=42,
                        help='Random seed for reproducibility')
    
    for arg in NON_IMPLEMENTED_ARGS:
        parser.add_argument(arg, action='store_true', default=False,
                            help=f'Argument {arg} is not yet implemented in pypalm')
    
    return parser

def validate_args(args):
    """Validate the parsed arguments."""
    # Check that input file exists and has valid extension
    if not os.path.exists(args.input):
        sys.exit(f"Error: Input file '{args.input}' does not exist")
    
    valid_input_extensions = ['.nii.gz', '.nii', '.csv', '.npy', '.txt']
    if not any(args.input.endswith(ext) for ext in valid_input_extensions):
        sys.exit(f"Error: Input file must be one of: {', '.join(valid_input_extensions)}")
    
    # Check mask file if provided
    if args.mask:
        if not os.path.exists(args.mask):
            sys.exit(f"Error: Mask file '{args.mask}' does not exist")
        
        if not (args.mask.endswith('.nii') or args.mask.endswith('.nii.gz')):
            sys.exit("Error: Mask file must be .nii or .nii.gz format")
    
    # Check design and contrast files
    for file_arg, arg_name in [(args.design, 'Design matrix'), (args.contrast, 'Contrast')]:
        if not os.path.exists(file_arg):
            sys.exit(f"Error: {arg_name} file '{file_arg}' does not exist")
        
        if not (file_arg.endswith('.csv') or file_arg.endswith('.npy')):
            sys.exit(f"Error: {arg_name} file must be .csv or .npy format")

    # Check f_contrast_indices file if provided
    if args.f_contrast_indices:
        if not os.path.exists(args.f_contrast_indices):
            sys.exit(f"Error: F-contrast indices file '{args.f_contrast_indices}' does not exist")
        
        if not (args.f_contrast_indices.endswith('.csv') or args.f_contrast_indices.endswith('.npy')):
            sys.exit("Error: F-contrast indices file must be .csv or .npy format")
    
    # Check exchangeability blocks file if provided
    if args.exchangeability_blocks and not os.path.exists(args.exchangeability_blocks):
        sys.exit(f"Error: Exchangeability blocks file '{args.exchangeability_blocks}' does not exist")
    
    # Handle variance groups. Can be either None, a path to a csv/npy, or "auto". If a file, let's load it.
    if args.variance_groups is not None:
        if args.variance_groups.lower() == "auto":
            pass
        elif not os.path.exists(args.variance_groups):
            sys.exit(f"Error: Variance groups file '{args.variance_groups}' does not exist")
        else:
            if not (args.variance_groups.endswith('.csv') or args.variance_groups.endswith('.npy')):
                sys.exit("Error: Variance groups file must be .csv or .npy format")

    # Handle accel parameter
    if isinstance(args.accel, str):
        if args.accel.lower() == "tail":
            args.accel = True
        else:
            print(f'Warning: accel method "{args.accel}" not recognized. Using "tail" instead. (GPD approximation)')
            args.accel = True
    elif args.accel is True:
        print("Acceleration enabled with default method: tail")

    # Handle p-value format options
    if args.save1_p is None:
        # User didn't explicitly specify save1_p
        if args.logp:
            # Only logp was specified, use that
            args.save1_p = False
        else:
            # Neither was specified, default to save1_p
            args.save1_p = True
    elif args.save1_p and args.logp:
        # Both were explicitly specified
        args.logp = False
        print("Warning: Both -save1-p and -logp were specified. Using -save1-p.")


    for arg in NON_IMPLEMENTED_ARGS:
        if getattr(args, arg[1:], False):
            print(f"Warning: Argument {arg} is not yet implemented in pypalm. Ignoring it.")
            print("Please open an issue on GitHub if you need this feature, or use the original PALM.")
    
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
        print("\nWarning: The following arguments are not yet implemented in pypalm:")
        for arg in unknown:
            print(f"  {arg}")
        print("\nThese may be available in the original PALM distribution by Anderson Winkler.")
        print("If your analysis requires these features, consider using the original PALM for now.\n")

    # Print parsed arguments for testing
    print("PYPALM - Permutation Analysis of Linear Models")
    print("=============================================")
    print(f"Input file: {args.input}")
    print(f"Design matrix: {args.design}")
    print(f"Contrast: {args.contrast}")
    print(f"Number of permutations: {args.n_permutations}")
    print(f"Output prefix: {args.output}")
    
    # Continue with the actual processing...
    # Your PALM implementation code would go here
    data = load_data(args.input)
    design = load_data(args.design)
    contrast = load_data(args.contrast)

    if args.f_contrast_indices:
        f_contrast_indices = load_data(args.f_contrast_indices)
        print(f"F-contrast indices: {f_contrast_indices}")
    else:
        f_contrast_indices = None

    stat_type = 't'
    input_is_nifti_like = is_nifti_like(data[0])

    output_prefix = get_output_path(args.output)
    if args.save_permutations:
        if input_is_nifti_like and args.mask is None:
            masker = NiftiMasker().fit(data[0])
            mask_img = masker.mask_img_
        else:
            mask_img = args.mask

        output_dir = os.path.join(os.path.dirname(output_prefix), "permutations")
        os.makedirs(output_dir, exist_ok=True)
        save_permutation_manager = SavePermutationManager(
            output_dir=output_dir,
            mask_img=mask_img,
            prefix=os.path.basename(output_prefix) if os.path.basename(output_prefix) else ""
        )
        on_permute_callback = save_permutation_manager.update
    else:
        on_permute_callback = None


    if input_is_nifti_like:
        print("Input data is NIfTI-like. Using volumetric dense analysis.")
        # Verify that we got a mask img
        if args.mask is None:
            print ("Warning: Mask image not provided. We'll try to move forward, but behavior may be unpredictable.")
        mask_img = args.mask

        stat_function = 'auto' if not args.pearson_r else pearson_r
        f_stat_function = 'auto' if not args.pearson_r else r_squared

        results = permutation_analysis_volumetric_dense(
            imgs=data,
            mask_img=mask_img,
            design=design,
            contrast=contrast,
            stat_function=stat_function,
            n_permutations=args.n_permutations,
            random_state=args.random_state,
            two_tailed=args.two_tailed,
            exchangeability_matrix = load_data(args.exchangeability_blocks) if args.exchangeability_blocks else None,
            vg_auto=True if args.variance_groups == "auto" else False,
            vg_vector=load_data(args.variance_groups) if (args.variance_groups is not None and args.variance_groups != "auto") else None,
            within=args.within,
            whole=args.whole,
            flip_signs=args.flip_signs,
            accel_tail=args.accel,
            demean=args.demean,
            f_stat_function=f_stat_function,
            f_contrast_indices=f_contrast_indices,
            f_only=args.f_only,
            correct_across_contrasts=args.correct_across_contrasts,
            on_permute_callback=on_permute_callback,
            tfce=args.tfce,
            save_1minusp=args.save1_p,
            save_neglog10p=args.logp,
        )

        for key, value in results.items():
            # If its not an F test (only testing single contrasts):
            if not key.endswith("f"):
                # Case if we assume equal variance and we are using default functions for contrast testing
                if stat_function == 'auto' and args.variance_groups is None:
                    # This means we are doing a t test.
                    if (re.search(r"stat_.*_c\d+", key)) or (re.search(r"stat_c\d+", key)):
                        key = key.replace("stat", "tstat")
                # Case if we have unequal variance between groups and we are using default functions for contrast testing
                elif stat_function == 'auto' and args.variance_groups is not None:
                    # This means we are doing an aspin_welch_v test.
                    if (re.search(r"stat_.*_c\d+", key)) or (re.search(r"stat_c\d+", key)):
                        key = key.replace("stat", "vstat")
                # Case if stat_function == pearson_r
                elif stat_function == pearson_r:
                    # This means we are doing a pearson r test.
                    if (re.search(r"stat_.*_c\d+", key)) or (re.search(r"stat_c\d+", key)):
                        key = key.replace("stat", "rstat")
            # If it IS an F test (testing multiple contrasts):
            else:
                # Case if we assume equal variance and we are using default functions for f testing
                if f_stat_function == 'auto' and args.variance_groups is None:
                    # In this case, we are actually doing an F test.
                    if (re.search(r"stat_.*_f", key)) or key.endswith("stat_f"):
                        key = key.replace("stat", "fstat")
                # Case if we have unequal variance between groups and we are using default functions for f testing
                elif f_stat_function == 'auto' and args.variance_groups is not None:
                    # In this case, we are actually doing a generalized f test, which is a G statistic.
                    if (re.search(r"stat_.*f", key)) or key.endswith("stat_f"):
                        key = key.replace("stat", "gstat")
                # Case if we f_stat_function == r_squared
                elif f_stat_function == r_squared:
                    # This means we are doing a r_squared test.
                    if (re.search(r"stat_.*_f", key)) or key.endswith("stat_f"):
                        key = key.replace("stat", "rsqstat")

            if "vox_" in key:
                nib.save(value, f"{output_prefix}_{key}.nii.gz")
            else:
                np.save(f"{output_prefix}_{key}.npy", value)

    else:
        results = permutation_analysis(
            data=data,
            design=design,
            contrast=contrast,
            stat_function='auto' if not args.pearson_r else pearson_r,
            n_permutations=args.n_permutations,
            random_state=args.random_state,
            two_tailed=args.two_tailed,
            exchangeability_matrix = load_data(args.exchangeability_blocks) if args.exchangeability_blocks else None,
            vg_auto=True if args.variance_groups == "auto" else False,
            vg_vector=load_data(args.variance_groups) if (args.variance_groups is not None and args.variance_groups != "auto") else None,
            within=args.within,
            whole=args.whole,
            flip_signs=args.flip_signs,
            accel_tail=args.accel,
            demean=args.demean,
            f_stat_function='auto' if not args.pearson_r else r_squared,
            f_contrast_indices=f_contrast_indices,
            f_only=args.f_only,
            correct_across_contrasts=args.correct_across_contrasts,
            on_permute_callback=on_permute_callback,
        )

        for key, value in results.items():
            if "_p" in key:
                if args.save1_p:
                    value = 1 - value

                elif args.logp:
                    value = -np.log10(value)

            np.save(f"{output_prefix}_dat_{key}.npy", value)

    print("Analysis complete. Results saved to output files.")
       
if __name__ == "__main__":
    main()