from typing import Tuple, Generator, List

import pandas as pd
from mrjob.job import MRJob
from mrjob.step import MRStep

from utils import get_most_frequent, merge_k_lists
from numpy.linalg import norm


class IrisClassificationJob(MRJob):
    """An MRJob for iris classification using KNN,"""

    def configure_args(self) -> None:
        """
        Configure the command line arguments for running the job.
        :return: None.
        """
        super(IrisClassificationJob, self).configure_args()
        self.add_passthru_arg("-k",
                              "--kNearest",
                              type=int,
                              help="How many closest neighbours to consider.")

    def mapper_csv(self,
                   input_path: str,
                   _: str) -> Generator[Tuple[int, Tuple[int, str, float]], None, None]:
        """
        Reads a CSV-format file and outputs key-value pairs that indicate the distance between the test samples and
        the train samples.
        :param input_path: The path to the CSV file.
        :param _: The URI to the CSV file (unused).
        :return: A generator of key-value pairs, where the key is the id of a test sample, and the value is a neighbour
        tuple containing the id of a train sample, its class, and the distance between the features of the test and
        train samples.
        """
        df = pd.read_csv(input_path)
        predictors = ['SepalLengthCm', 'SepalWidthCm', 'PetalLengthCm', 'PetalWidthCm']

        test_df = df[df['Species'].isnull()]
        train_df = df[df['Species'].notnull()]

        # Inplace modification of the dataframes results in an encoding error (bytes not 'str' required).
        # This is probably because the mapper is a raw_mapper.
        test_df_deep_copy = test_df.copy(deep=True)
        train_df_deep_copy = train_df.copy(deep=True)

        # Min-max normalize the predictors
        for column in predictors:
            column_min = train_df[column].min()
            column_max = train_df[column].max()
            test_df_deep_copy[column] = (test_df[column] - column_min) / (column_max - column_min)
            train_df_deep_copy[column] = (train_df[column] - column_min) / (column_max - column_min)

        # Iterate through test_sample, train_sample pairs:
        for _, test_sample in test_df_deep_copy.iterrows():
            for _, train_sample in train_df_deep_copy.iterrows():
                distance = norm(train_sample[predictors].to_numpy() -
                                test_sample[predictors].to_numpy())
                yield test_sample['Id'], (train_sample['Id'], train_sample['Species'], distance)

    def combiner(self,
                 key: int,
                 values: List[Tuple[int, str, float]]) -> Generator[Tuple[int, Tuple[int, str, float]], None, None]:
        """
        Sort the mapper-node local neighbours of a test node. If there are multiple mapper nodes, this can be done in
        parallel. The built-in sort is O(nlog(n)), and the min-heap merging of K sorted lists is O(nlog(k)). More mapper
        nodes results in more efficient merging and more parallel sorting.

        :param key: The id of a test sample.
        :param values: A mapper-node local list of neighbour tuples, with the id, class, and distance.
        :return: A generator of key-value pairs where the key is the id of the test sample and the value is the sorted
        list of mapper-node local neighbour tuples.
        """
        sorted_local_neighbours = sorted(values, key=lambda x: x[2])
        yield key, sorted_local_neighbours

    def reducer(self,
                key: int,
                values: List[List[Tuple[int, str, float]]]) -> Generator[Tuple[int, str], None, None]:
        """
        Merges the sorted list of neighbours from the combiner, selects the first K (specified by the command line
        argument -k) and determines the predominant class.

        :param key: The id of a test sample.
        :param values: A list of sorted lists of key's neighbours, each from the combiner in a different mapper node.
        :return: A generator of key-value pairs where the key is the id of the test sample and the value is the
        predicted class based on the KNN algorithm.
        """

        neighbours = merge_k_lists(values)
        k_nearest = neighbours[:self.options.kNearest]
        class_ = get_most_frequent(k_nearest)
        yield key, class_

    def steps(self):
        """
        Define the job steps.
        :return: The list of the steps of the job.
        """
        return [
            MRStep(mapper_raw=self.mapper_csv,
                   combiner=self.combiner,
                   reducer=self.reducer)
        ]


if __name__ == '__main__':
    job = IrisClassificationJob().run()