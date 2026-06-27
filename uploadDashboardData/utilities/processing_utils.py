import pandas as pd
import numpy as np

def process_names(df):
    """
    Process students' names and IDs for analysis and merging

    Keyword arguments:
    df -- pandas dataframe of student responses to the PLIC
    """
    df['QStudentID'] = df['QStudentID'].astype(str).str.split('@').str.get(0).str.lower() # Keep only first part of email addresses and take the lower case of all ids
    df['FullName'] = (df['QLastName'].astype(str).str.lower() + df['QFirstName'].astype(str).str.lower()).str.replace(r'\W', '', regex=True) # Get full name in lower case with no white space
    df['BackName'] = (df['QFirstName'].astype(str).str.lower() + df['QLastName'].astype(str).str.lower()).str.replace(r'\W', '', regex=True) # Get reverse full name in lower case with no white space
    df.loc[df['FullName'].map(len) <= 2, 'FullName'] = '' # Keep only full names with more than 2 characters
    df = df.drop_duplicates(subset = ['FullName']).drop_duplicates(subset = ['QStudentID']) # Drop second entry if there are duplicate full names

    return df

def match_responses(post_df, pre_df = None):
    '''
    This function matches the pre-survey responses to the post-survey responses.
    If no pre-survey was done, then no matching occurs and the post-survey is returned with proper formatting.
    Proper formatting means a column that contains student names and IDs. 
    '''
    
    if pre_df is None:
        # Run process_names to properly format QStudentID and drop duplicates
        post_df = process_names(post_df)
        # Drop unnecessary columns
        post_df = post_df.drop(columns = ['FullName', 'BackName'])
                
        # If there is only a post-survey, format the post-survey for generalization by filling the pre-columns with NaN
        merged_df = pd.concat({
                **{f"{col}_PRE": pd.Series([np.nan] * len(post_df), index=post_df.index) for col in post_df.columns},
                **{f"{col}_POST": post_df[col] for col in post_df.columns}
            }, axis=1)
    else:
        # Otherwise, match the pre- and post-survey data
        # Prepare data for matching
        pre_df = process_names(pre_df)
        post_df = process_names(post_df)
        
        # merge on forward and backwards names, and IDs
        fullname_merge_df = pd.merge(left = pre_df, right = post_df, how = 'inner', on = ['FullName'], suffixes=('_PRE', '_POST'))
        backname_merge_df = pd.merge(left = pre_df, right = post_df, how = 'inner', 
                                     left_on = ['FullName'], right_on = ['BackName'], suffixes=('_PRE', '_POST'))
        id_merge_df = pd.merge(left = pre_df, right = post_df, how = 'inner', 
                               on = ['QStudentID'], suffixes=('_PRE', '_POST'))
        
        # id_merge_df has only one QStudentID column, but we want one for pre and post, so let's handle that here
        id_merge_df = id_merge_df.rename(columns = {'QStudentID':'QStudentID_PRE'})
        id_merge_df['QStudentID_POST'] = id_merge_df['QStudentID_PRE'] # create duplicate ID column for merging with names dataframes

        # Put all these merged dataframes together and drop duplicates
        merged_df = pd.concat([fullname_merge_df, backname_merge_df, id_merge_df], 
                              axis = 0, join = 'inner'
                             ).drop_duplicates().reset_index(drop = True)
        
        # Drop unnecessary columns
        merged_df = merged_df.drop(columns = ['BackName_PRE', 'BackName_POST'])
        
        # Now we want to make sure it has the pre- and post-survey exclusive responses
        # Drop the rows that are actually successfully matched
        pre_df = pre_df[~pre_df['ResponseID'].isin(merged_df['ResponseID_PRE'])]
        post_df = post_df[~post_df['ResponseID'].isin(merged_df['ResponseID_POST'])]
        
        # Drop FullName and BackName because we no longer need them
        pre_df = pre_df.drop(columns = ['FullName', 'BackName'])
        post_df = post_df.drop(columns = ['FullName', 'BackName'])
        
        # Add suffixes to the column titles for merging
        pre_df.columns = pre_df.columns + '_PRE'
        post_df.columns = post_df.columns + '_POST'
        
        # Add onto merged_df the pre- and post-survey only responses
        merged_df = pd.concat([merged_df, pre_df, post_df], 
                              axis = 0, join = 'outer'
                             ).reset_index(drop = True)

    # Create columns at the beginning of the dataframe that specify identifying information across pre- and post-survey data
    # Use the post-survey data unless it is missing
    merged_df.insert(0, "FirstName", merged_df["QFirstName_POST"].fillna(merged_df["QFirstName_PRE"]))
    merged_df.insert(0, "LastName", merged_df["QLastName_POST"].fillna(merged_df["QLastName_PRE"]))
    merged_df.insert(0, "StudentID", merged_df["QStudentID_POST"].fillna(merged_df["QStudentID_PRE"]))

    return merged_df

def simplify_columns(df, column_ordering, instructor_id, course_type, class_size, plic_version = 'June2025'):
    '''
    This function drops unnecessary columns and rearranges the columns to be in the correct order.
    '''
    df = df.rename(
        columns = {
            'QDem_TaskPref_6_PRE': 'QDem_TaskPref_Equipment_PRE',
            'QDem_TaskPref_1_PRE': 'QDem_TaskPref_Notes_PRE',
            'QDem_TaskPref_2_PRE': 'QDem_TaskPref_Analysis_PRE',
            'QDem_TaskPref_3_PRE': 'QDem_TaskPref_Managing_PRE',
            'QDem_TaskPref_4_PRE': 'QDem_TaskPref_Theory_PRE',
            'QDem_TaskPref_5_PRE': 'QDem_TaskPref_Other_PRE',
            'QDem_TaskPref_5_TEXT_PRE': 'QDem_TaskPref_Other_TEXT_PRE',
            'QDem_TaskDone_1_PRE': 'QDem_TaskDone_Equipment_PRE',
            'QDem_TaskDone_2_PRE': 'QDem_TaskDone_Notes_PRE',
            'QDem_TaskDone_3_PRE': 'QDem_TaskDone_Analysis_PRE',
            'QDem_TaskDone_4_PRE': 'QDem_TaskDone_Managing_PRE',
            'QDem_TaskDone_5_PRE': 'QDem_TaskDone_Theory_PRE',
            'QDem_TaskDone_6_PRE': 'QDem_TaskDone_Other_PRE',
            'QDem_TaskDone_6_TEXT_PRE': 'QDem_TaskDone_Other_TEXT_PRE',
            'QDem_RoleDist_1_PRE': 'QDem_RoleDist_Share_PRE',
            'QDem_RoleDist_5_PRE': 'QDem_RoleDist_Rotate_PRE',
            'QDem_RoleDist_3_PRE': 'QDem_RoleDist_Split_PRE',
            'QDem_RoleDist_12_PRE': 'QDem_RoleDist_Other_PRE',
            'QDem_RoleDist_12_TEXT_PRE': 'QDem_RoleDist_Other_TEXT_PRE',
            'QDem_TaskPref_6_POST': 'QDem_TaskPref_Equipment_POST',
            'QDem_TaskPref_1_POST': 'QDem_TaskPref_Notes_POST',
            'QDem_TaskPref_2_POST': 'QDem_TaskPref_Analysis_POST',
            'QDem_TaskPref_3_POST': 'QDem_TaskPref_Managing_POST',
            'QDem_TaskPref_4_POST': 'QDem_TaskPref_Theory_POST',
            'QDem_TaskPref_5_POST': 'QDem_TaskPref_Other_POST',
            'QDem_TaskPref_5_TEXT_POST': 'QDem_TaskPref_Other_TEXT_POST',
            'QDem_TaskDone_1_POST': 'QDem_TaskDone_Equipment_POST',
            'QDem_TaskDone_2_POST': 'QDem_TaskDone_Notes_POST',
            'QDem_TaskDone_3_POST': 'QDem_TaskDone_Analysis_POST',
            'QDem_TaskDone_4_POST': 'QDem_TaskDone_Managing_POST',
            'QDem_TaskDone_5_POST': 'QDem_TaskDone_Theory_POST',
            'QDem_TaskDone_6_POST': 'QDem_TaskDone_Other_POST',
            'QDem_TaskDone_6_TEXT_POST': 'QDem_TaskDone_Other_TEXT_POST',
            'QDem_RoleDist_1_POST': 'QDem_RoleDist_Share_POST',
            'QDem_RoleDist_5_POST': 'QDem_RoleDist_Rotate_POST',
            'QDem_RoleDist_3_POST': 'QDem_RoleDist_Split_POST',
            'QDem_RoleDist_12_POST': 'QDem_RoleDist_Other_POST',
            'QDem_RoleDist_12_TEXT_POST': 'QDem_RoleDist_Other_TEXT_POST'
        })

    df = df[column_ordering.columns]

    # Make first four columns describe the whole course (and survey)
    df.insert(0, "Class_ID", instructor_id)
    df.insert(1, "Course Type", course_type)
    df.insert(2, "Class_Size", class_size)
    df.insert(3, "PLIC_Version", plic_version)

    # Mapping dictionary
    #course_type_mapping = {
    #    1: "Introductory (Algebra based)",
    #    2: "Introductory (Calculus based)",
    #    3: "Sophomore",
    #    4: "Junior",
    #    5: "Senior",
    #    6: "High School",
    #    7: "Graduate"
    #}
    course_type_mapping = {
        1: "Introductory",
        2: "Beyond Introductory",
    }

    # Apply the mapping
    df["Course Type"] = df["Course Type"].map(course_type_mapping)

    return df