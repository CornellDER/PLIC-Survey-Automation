import pandas as pd
import numpy as np

def validate_responses(df):
    """
    Validate survey responses to the PLIC

    Keyword arguments:
    df -- pandas dataframe of student responses to the PLIC
    """

    # Check consent and age
    df['Valid'] = np.nan # start with empty column
    df.loc[(df['QConsent'] == 1) & (df['Q6d'] == 2), 'Valid'] = 1 # if they consent and are 18 or older, it's valid
    df.loc[(df['QConsent'] == 0) | ((df['QConsent'] == 1) & (df['Q6d'] == 1)), 'Valid'] = 0 # if they do not consent or are not 18, it's not valid

    # Check survey finished
    df = df[df['Finished'] == 1]

    # Check at least 30s spent on at least one page
    df = df[(df['Qt1_3'] >= 30) | (df['Qt2_3'] >= 30) | (df['Qt3_3'] >= 30) | (df['Qt4_3'] >= 30)]

    # Check name and ID given
    df = df.dropna(how = 'all', subset = ['QStudentID', 'QLastName', 'QFirstName']) # drops responses with no identifying information, just in case
    
    # Reset index for cleanliness
    df = df.reset_index(drop=True)

    return df

def score_plic_questions(df, plic_weights):
    '''
    This function narrows each PLIC question into a single score for that one item and adds it on as a new column to the dataframe.
    '''
    plic_questions = ['Q1b', 'Q2b', 'Q3b', 'Q3d', 'Q4b', 'Q1e', 'Q2e', 'Q3e']

    for plic_question in plic_questions: # Loop over questions
        # Get response choices for question
        question_items = [c for c in plic_weights.columns if plic_question in c]

        # Q1b, Q2b, and Q3b are scored differently than the rest
        # A student can select two answers that have opposite reasoning, but they should only be able to get points for one of those
        if plic_question in ['Q1b', 'Q2b', 'Q3b']:
            # narrow down responses, fill empty responses with 0, and make sure everything is a float
            temp_question_df = simplify_plic_questions(df, plic_question)
        else:
            # fill empty responses with 0 and make sure everything is a float
            temp_question_df = df[question_items].fillna(0).astype(float)
        
        # Get response choices that will be scored for question
        # This line is added so that we do not have to write a line for both the if and else statements
        scored_items = [c for c in temp_question_df.columns]
        
        # Pull response choice weights from plic_weights
        question_weights = (plic_weights[scored_items]).iloc[0]

        # Get the two largest weights, sorted; that is, find the maximum possible score on this question
        ordered_weights = question_weights.nlargest(2)

        # Get normalizations for each student, mapping number of selected items
        density_series = (
            temp_question_df.sum(axis = 1)
            .clip(upper = 2)
            .map({0.0:1, 1.0:ordered_weights.iloc[0],  2.0:ordered_weights.sum()})
        )

        # Normalized scores for each student on the question
        df[plic_question.upper()] = (temp_question_df * question_weights).sum(axis = 1) / density_series

    return df

def simplify_plic_questions(df, question):
    '''
    This function makes a temporary dataframe that is used for scoring Q1b, Q2b, and Q3b. 
    '''
    
    # Start with an empty DataFrame
    temp_question_df = pd.DataFrame()

    if question == 'Q1b':
        column_pairs = {
            "Q1b_2": "Q1b_37",
            "Q1b_5": "Q1b_33",
            "Q1b_8": "Q1b_34",
            "Q1b_28": "Q1b_36"
        }
        other_question = "Q1b_19"
    
    elif question == 'Q2b':
        column_pairs = {
            "Q2b_8":  "Q2b_39",
            "Q2b_11": "Q2b_40",
            "Q2b_21": "Q2b_41",
            "Q2b_2":  "Q2b_42",
            "Q2b_9":  "Q2b_43",
            "Q2b_36": "Q2b_44",
            "Q2b_6":  "Q2b_45",
            "Q2b_1":  "Q2b_46",
        }
        other_question = "Q2b_38"

    elif question == 'Q3b':
        column_pairs = {
            "Q3b_8":  "Q3b_39",
            "Q3b_11": "Q3b_40",
            "Q3b_21": "Q3b_41",
            "Q3b_2":  "Q3b_42",
            "Q3b_9":  "Q3b_43",
            "Q3b_36": "Q3b_44",
            "Q3b_6":  "Q3b_45",
            "Q3b_1":  "Q3b_46"
        }
        other_question = "Q3b_38"

    # Add merged columns with logic: 1 if either column is 1+, else 0
    for col1, col2 in column_pairs.items():
        temp_question_df[col1] = np.where((df[col1].fillna(0).astype(float) + df[col2].fillna(0).astype(float)) >= 1.0, 1.0, 0.0)

    # Add "Other" questions as-is with fillna(0) and float conversion
    temp_question_df[other_question] = df[other_question].fillna(0).astype(float)

    return temp_question_df

def score_constructs(df):
    '''
    This function scores each construct by taking means of each construct's questions.
    Note: this function accounts for reverse coding of belonging items. 
    '''
    
    models_questions = ['Q1B', 'Q2B', 'Q3B', 'Q3D']
    methods_questions = ['Q4B']
    actions_questions = ['Q1E', 'Q2E', 'Q3E']
    
    se_questions = ["QDem_SE_1", "QDem_SE_2", "QDem_SE_3", "QDem_SE_4", "QDem_SE_5",
                    "QDem_SE_6", "QDem_SE_7", "QDem_SE_8", "QDem_SE_9", "QDem_SE_10"]
    pa_questions = ["QDem_Constructs_QDem_PA_1", "QDem_Constructs_QDem_PA_2", "QDem_Constructs_QDem_PA_3", "QDem_Constructs_QDem_PA_4"]
    bel_questions = ["QDem_Constructs_QDem_Bel_1", "QDem_Constructs_QDem_Bel_2", "QDem_Constructs_QDem_Bel_3",
                     "QDem_Constructs_QDem_Bel_4", "QDem_Constructs_QDem_Bel_5", "QDem_Constructs_QDem_Bel_6"]
    reverse_bel_questions = ["QDem_Constructs_QDem_Bel_1", "QDem_Constructs_QDem_Bel_3",
                             "QDem_Constructs_QDem_Bel_5", "QDem_Constructs_QDem_Bel_6"]
    rec_questions = ["QDem_Constructs_QDem_Rec_1", "QDem_Constructs_QDem_Rec_2", 
                     "QDem_Constructs_QDem_Rec_3", "QDem_Constructs_QDem_Rec_4"]

    ## PLIC Scoring
    df['models'] = df[models_questions].mean(axis=1)
    df['methods'] = df[methods_questions].mean(axis=1)
    df['actions'] = df[actions_questions].mean(axis=1)
    df['TotalScore'] = df[models_questions + methods_questions + actions_questions].sum(axis=1)
    # There are 8 questions on the PLIC, so we normalize by dividing by 8
    df['NormScore'] = (df['TotalScore'])/8

    ## Construct Scoring
    # Calculate the student attitude constructs but only when they complete every question for that construct
    df['SelfEfficacy'] = df[se_questions].mean(axis=1).where(df[se_questions].notna().all(axis=1))
    df['PerceivedAgency'] = df[pa_questions].mean(axis=1).where(df[pa_questions].notna().all(axis=1))

    # Belonging has reverse mapped items, we'll handle this separately
    # Make a copy of just the relevant columns
    bel_df = df[bel_questions].copy()
    # Reverse-code the specified columns
    for col in reverse_bel_questions:
        bel_df[col] = 6 - bel_df[col]
    # Calculate the mean only for rows with all non-NaNs
    df['Belonging'] = bel_df.mean(axis=1).where(bel_df.notna().all(axis=1))
    
    df['Recognition'] = df[rec_questions].mean(axis=1).where(df[rec_questions].notna().all(axis=1))

    # Round all entries (nine is used because prior code was rounded to that precision)
    round_columns = models_questions + methods_questions + actions_questions + ['models', 'methods', 'actions', 'TotalScore',
                                                                                'NormScore', 'SelfEfficacy', 'PerceivedAgency', 
                                                                                'Belonging', 'Recognition']
    for col in round_columns:
        df[col] = df[col].round(9)

    return df