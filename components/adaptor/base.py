from abc import ABC, abstractmethod
from typing import List, Dict, Any, Union
class BaseTimeSeriesStorage(ABC):
    """
    Abstract base class for time series storage providers.
    Defines the interface for historical data retrieval.
    """

    @abstractmethod
    async def get_history(self, roomid: str, starttime: str, endtime: str) -> Union[List[Dict[str, Any]], Dict[str, str]]:
        """
        Retrieves historical data for a given room and time range.
        Returns a list of events containing 'created_at' and all dynamic fields. 
        In case of error, returns a dict with an 'error' key.
        """
        pass