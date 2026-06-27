import pandas as pd
from utilities.qualtrics_utils import get_cis_response_data, download_responses_as_df
from utilities.scoring_utils import validate_responses, score_plic_questions, score_constructs
from utilities.processing_utils import match_responses, simplify_columns

def compile_course_data(instructor_id):
    """
    Create a dataframe with all the (post- and possibly pre-survey) data for a course.
    This function returns a dataframe that is formatted to be easily appended to the dashboard data file.

    Keyword arguments:
    instructor_id -- string specifying the instructor's response ID in the course information survey
    """
    # Obtain survey data from instructor ID
    result = get_cis_response_data(instructor_id)
    
    # Load data we will use in data prep
    plic_weights = pd.read_csv('utilities/QuestionText_June2025.csv', skiprows=[1])
    column_df = pd.read_csv('utilities/ColumnOrdering_June2025.csv')
    
    # By default there is a post-survey. We will handle that first
    # Download
    post_df = download_responses_as_df(result["post_id"])

    # Validate
    post_df = validate_responses(post_df)
    
    # Score
    post_df = score_plic_questions(post_df, plic_weights)
    post_df = score_constructs(post_df)
    
    # If there is a pre-survey, download and prep it
    if result["pre_id"] is not None:
        # Download
        pre_df = download_responses_as_df(result["pre_id"])
        # Validate
        pre_df = validate_responses(pre_df)
        # Score
        pre_df = score_plic_questions(pre_df, plic_weights)
        pre_df = score_constructs(pre_df)
    else:
        # Define pre_df as None for match_responses
        pre_df = None
    
    # Match
    matched_df = match_responses(post_df = post_df, pre_df = pre_df)
    
    # Simplify columns
    finalized_df = simplify_columns(df = matched_df, column_ordering = column_df, 
                                    instructor_id = instructor_id, course_type = result["course_type"], 
                                    class_size = result["class_size"])
    
    # Return the data
    return finalized_df