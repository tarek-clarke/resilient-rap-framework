"""
NHL Adapter
-----------
Real-time NHL play-by-play event streaming from the official NHL Stats API.
Connects to statsapi.web.nhl.com to pull game events (shots, goals, hits, etc.) as event streams.
"""
import requests
import polars as pl
from datetime import datetime
from typing import Optional, List
from modules.base_ingestor import BaseIngestor


class NHLAdapter(BaseIngestor):
    """
    Adapter for ingesting NHL play-by-play events from the official NHL Stats API.
    Simulates live streaming environment with game event data.
    
    API Documentation: https://statsapi.web.nhl.com/
    Endpoint: https://statsapi.web.nhl.com/api/v1/game/{gameId}/feed/live
    
    Game ID Format: SSSSTTTGGGG
    - SSSS: Season (e.g., 2024 for 2024-25)
    - TTT: Game type (02=regular season, 03=playoffs)
    - GGGG: Game number
    """
    
    def __init__(
        self, 
        game_id: str,
        source_name: str = "NHL_Stats_API",
        target_schema: Optional[list] = None
    ):
        """
        Initialize the NHL adapter.
        
        Args:
            game_id: NHL game ID (e.g., "2024020001" for first game of 2024-25 regular season)
            source_name: Name of the data source for lineage tracking
            target_schema: Gold standard schema for semantic reconciliation
        """
        # Define the Gold Standard Schema for NHL play-by-play events
        if not target_schema:
            target_schema = [
                "Event Type",
                "Event Time",
                "Period",
                "Player Name",
                "Team",
                "X Coordinate",
                "Y Coordinate",
                "Shot Type",
                "Shot Distance",
                "Shot Result",
                "Assist 1",
                "Assist 2",
                "Penalty Type",
                "Penalty Minutes"
            ]
        
        super().__init__(source_name, target_schema)
        
        self.base_url = "https://api-web.nhle.com/v1"
        self.game_id = game_id
        self.raw_data = None
        
    def connect(self):
        """
        Validate API connectivity by making a test request.
        """
        try:
            # Test connection with game endpoint (new NHL API structure)
            response = requests.get(
                f"{self.base_url}/gamecenter/{self.game_id}/play-by-play",
                timeout=10
            )
            response.raise_for_status()
            
            game_info = response.json()
            if not game_info:
                raise ValueError(f"Game {self.game_id} not found or invalid")
            
            # Extract game metadata from new API structure
            away_team = game_info.get("awayTeam", {}).get("name", {}).get("default", "Unknown")
            home_team = game_info.get("homeTeam", {}).get("name", {}).get("default", "Unknown")
            
            self.record_lineage(
                "connected_to_nhl_stats_api",
                metadata={
                    "game_id": self.game_id,
                    "away_team": away_team,
                    "home_team": home_team,
                    "api_status": "connected"
                }
            )
            
        except requests.exceptions.RequestException as e:
            self.record_error("connection", e)
            raise ConnectionError(f"Failed to connect to NHL Stats API: {str(e)}")
    
    def extract_raw(self):
        """
        Fetch raw play-by-play event data from the NHL Stats API.
        Includes exponential backoff retry logic for reliability.
        
        Returns:
            Raw JSON response from the API
        """
        import time
        
        max_retries = 3
        timeout = 60
        
        for attempt in range(max_retries):
            try:
                # Fetch game play-by-play with new API structure
                response = requests.get(
                    f"{self.base_url}/gamecenter/{self.game_id}/play-by-play",
                    timeout=timeout
                )
                response.raise_for_status()
                
                self.raw_data = response.json()
                
                # Extract event count from new API structure
                event_count = 0
                if isinstance(self.raw_data, dict):
                    plays = self.raw_data.get("plays", [])
                    event_count = len(plays)
                
                self.record_lineage(
                    "data_extracted",
                    metadata={
                        "endpoint": f"/v1/gamecenter/{self.game_id}/play-by-play",
                        "events_fetched": event_count,
                        "retry_attempt": attempt + 1
                    }
                )
                
                return self.raw_data
                
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    # Exponential backoff: 2s, 4s, 8s
                    wait_time = 2 ** (attempt + 1)
                    self.record_lineage(
                        "api_timeout_retry",
                        metadata={
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "wait_seconds": wait_time
                        }
                    )
                    time.sleep(wait_time)
                else:
                    self.record_error("extraction_timeout", Exception(f"API timeout after {max_retries} retries"))
                    raise RuntimeError(f"Failed to extract data from NHL Stats API after {max_retries} retries: Timeout")
            except requests.exceptions.RequestException as e:
                self.record_error("extraction", e)
                raise RuntimeError(f"Failed to extract data from NHL Stats API: {str(e)}")
    def parse(self, raw):
        """
        Parse the raw JSON response and map to internal field names.
        
        The NHL API returns play-by-play events including:
        - Shot events (with coordinates, shot type, distance)
        - Goal events (with scorers and assists)
        - Hit events (with player and team)
        - Penalty events (with type and duration)
        - Faceoff events (with winner and coordinates)
        
        We map these to potentially "messy" internal field names to test
        the semantic reconciliation layer.
        
        Args:
            raw: Raw JSON response from the API
            
        Returns:
            List of parsed event records
        """
        if not raw or not isinstance(raw, dict):
            self.record_error("parsing", Exception("Invalid or empty raw data"))
            return []
        
        parsed_data = []
        
        # Extract plays from new API structure
        plays = raw.get("plays", [])
        
        # Get roster data for player name lookups
        roster_spots = raw.get("rosterSpots", [])
        player_lookup = {}
        for player in roster_spots:
            player_id = player.get("playerId")
            if player_id:
                first_name = player.get("firstName", {}).get("default", "")
                last_name = player.get("lastName", {}).get("default", "")
                full_name = f"{first_name} {last_name}".strip()
                player_lookup[player_id] = {
                    "name": full_name,
                    "jersey": player.get("sweaterNumber")
                }
        
        # Get team information
        away_team = raw.get("awayTeam", {})
        home_team = raw.get("homeTeam", {})
        
        for play in plays:
            type_desc = play.get("typeDescKey", "")
            
            # Skip non-interesting events
            if type_desc in ["period-start", "period-end", "game-end", "stoppage", 
                            "period-official", "game-scheduled", "delayed-game"]:
                continue
            
            # Handle timestamp
            timestamp = raw.get("gameDate")
            if not timestamp:
                timestamp = datetime.utcnow().isoformat()
            
            # Base event data
            period_desc = play.get("periodDescriptor", {})
            details = play.get("details", {})
            
            # Map API fields to internal format with intentional variations
            parsed_record = {
                "event_timestamp": timestamp,
                "event_type_code": type_desc.upper(),  # Map: typeDescKey -> event_type_code
                "period_num": period_desc.get("number"),
                "period_time_elapsed": play.get("timeInPeriod"),
                "event_idx": play.get("eventId"),
            }
            
            # Add coordinate data if available
            if details.get("xCoord") is not None:
                parsed_record["coord_x"] = details.get("xCoord")  # Map: xCoord -> coord_x
                parsed_record["coord_y"] = details.get("yCoord")  # Map: yCoord -> coord_y
                parsed_record["zone_code"] = details.get("zoneCode")  # O=offensive, D=defensive, N=neutral
            
            # Extract player information based on event type
            if type_desc in ["shot-on-goal", "missed-shot", "blocked-shot"]:
                shooter_id = details.get("shootingPlayerId")
                if shooter_id and shooter_id in player_lookup:
                    parsed_record["player_name_full"] = player_lookup[shooter_id]["name"]
                    parsed_record["player_jersey_number"] = player_lookup[shooter_id]["jersey"]
                
                parsed_record["shot_type_desc"] = details.get("shotType")  # Map: shotType -> shot_type_desc
                parsed_record["shot_result"] = "SAVE" if type_desc == "shot-on-goal" else type_desc.upper()
                
                # Team information
                event_owner_team_id = details.get("eventOwnerTeamId")
                if event_owner_team_id == away_team.get("id"):
                    parsed_record["team_name"] = away_team.get("name", {}).get("default", "")
                    parsed_record["team_abbrev"] = away_team.get("abbrev", "")
                elif event_owner_team_id == home_team.get("id"):
                    parsed_record["team_name"] = home_team.get("name", {}).get("default", "")
                    parsed_record["team_abbrev"] = home_team.get("abbrev", "")
            
            if type_desc == "goal":
                scorer_id = details.get("scoringPlayerId")
                if scorer_id and scorer_id in player_lookup:
                    parsed_record["player_name_full"] = player_lookup[scorer_id]["name"]
                    parsed_record["player_jersey_number"] = player_lookup[scorer_id]["jersey"]
                
                parsed_record["shot_type_desc"] = details.get("shotType")
                parsed_record["shot_result"] = "GOAL"
                
                # Assists
                assist1_id = details.get("assist1PlayerId")
                assist2_id = details.get("assist2PlayerId")
                if assist1_id and assist1_id in player_lookup:
                    parsed_record["assist_1_name"] = player_lookup[assist1_id]["name"]
                if assist2_id and assist2_id in player_lookup:
                    parsed_record["assist_2_name"] = player_lookup[assist2_id]["name"]
                
                # Team information
                event_owner_team_id = details.get("eventOwnerTeamId")
                if event_owner_team_id == away_team.get("id"):
                    parsed_record["team_name"] = away_team.get("name", {}).get("default", "")
                    parsed_record["team_abbrev"] = away_team.get("abbrev", "")
                elif event_owner_team_id == home_team.get("id"):
                    parsed_record["team_name"] = home_team.get("name", {}).get("default", "")
                    parsed_record["team_abbrev"] = home_team.get("abbrev", "")
            
            if type_desc == "penalty":
                penalty_id = details.get("committedByPlayerId")
                if penalty_id and penalty_id in player_lookup:
                    parsed_record["player_name_full"] = player_lookup[penalty_id]["name"]
                    parsed_record["player_jersey_number"] = player_lookup[penalty_id]["jersey"]
                
                parsed_record["penalty_type_desc"] = details.get("typeCode")
                parsed_record["penalty_minutes"] = details.get("duration")
                
                # Team information
                event_owner_team_id = details.get("eventOwnerTeamId")
                if event_owner_team_id == away_team.get("id"):
                    parsed_record["team_name"] = away_team.get("name", {}).get("default", "")
                    parsed_record["team_abbrev"] = away_team.get("abbrev", "")
                elif event_owner_team_id == home_team.get("id"):
                    parsed_record["team_name"] = home_team.get("name", {}).get("default", "")
                    parsed_record["team_abbrev"] = home_team.get("abbrev", "")
            
            if type_desc == "hit":
                hitter_id = details.get("hittingPlayerId")
                hittee_id = details.get("hitteePlayerId")
                if hitter_id and hitter_id in player_lookup:
                    parsed_record["player_name_full"] = player_lookup[hitter_id]["name"]
                if hittee_id and hittee_id in player_lookup:
                    parsed_record["hit_target_player"] = player_lookup[hittee_id]["name"]
            
            if type_desc == "faceoff":
                winner_id = details.get("winningPlayerId")
                if winner_id and winner_id in player_lookup:
                    parsed_record["player_name_full"] = player_lookup[winner_id]["name"]
            
            # Add game metadata
            parsed_record["game_id"] = self.game_id
            
            parsed_data.append(parsed_record)
        
        self.record_lineage(
            "data_parsed",
            metadata={
                "records_parsed": len(parsed_data),
                "field_mappings": {
                    "typeDescKey": "event_type_code",
                    "xCoord": "coord_x",
                    "yCoord": "coord_y",
                    "shotType": "shot_type_desc",
                    "playerId_name": "player_name_full"
                }
            }
        )
        
        return parsed_data
    
    def validate(self, parsed):
        """
        Validate the parsed event data.
        
        Checks:
        - Data not empty
        - Required fields present
        - Values within reasonable ranges
        
        Args:
            parsed: List of parsed records
        """
        if not parsed:
            self.record_error("validation", Exception("No data to validate"))
            return
        
        validation_errors = []
        
        for idx, record in enumerate(parsed):
            # Check for required fields
            required_fields = ["event_timestamp", "event_type_code", "game_id"]
            missing_fields = [f for f in required_fields if f not in record or not record[f]]
            
            if missing_fields:
                validation_errors.append({
                    "record_index": idx,
                    "error": "missing_required_fields",
                    "fields": missing_fields
                })
            
            # Validate period number (1-5 for regulation + OT/SO)
            if record.get("period_num") is not None:
                period = record["period_num"]
                if period < 1 or period > 5:
                    validation_errors.append({
                        "record_index": idx,
                        "error": "period_out_of_range",
                        "value": period
                    })
            
            # Validate coordinates (NHL rink: -100 to 100 for x, -42.5 to 42.5 for y)
            if record.get("coord_x") is not None:
                x = record["coord_x"]
                if x < -100 or x > 100:
                    validation_errors.append({
                        "record_index": idx,
                        "error": "x_coordinate_out_of_range",
                        "value": x
                    })
            
            if record.get("coord_y") is not None:
                y = record["coord_y"]
                if y < -42.5 or y > 42.5:
                    validation_errors.append({
                        "record_index": idx,
                        "error": "y_coordinate_out_of_range",
                        "value": y
                    })
        
        if validation_errors:
            self.record_lineage(
                "validation_warnings",
                metadata={
                    "total_errors": len(validation_errors),
                    "errors": validation_errors[:10]  # Log first 10 errors
                }
            )
    
    def normalize(self, parsed):
        """
        Normalize the parsed data into a consistent format.
        
        - Ensures all timestamps are properly formatted
        - Converts null values to appropriate defaults
        - Ensures numeric fields are proper types
        
        Args:
            parsed: List of parsed records
            
        Returns:
            Normalized list of records
        """
        normalized_data = []
        
        for record in parsed:
            normalized_record = record.copy()
            
            # Ensure numeric fields are correct types
            numeric_int_fields = {
                "period_num": int,
                "event_idx": int,
                "penalty_minutes": int,
            }
            
            numeric_float_fields = {
                "coord_x": float,
                "coord_y": float,
                "shot_distance_ft": float,
            }
            
            for field, dtype in numeric_int_fields.items():
                if field in normalized_record and normalized_record[field] is not None:
                    try:
                        normalized_record[field] = dtype(normalized_record[field])
                    except (ValueError, TypeError):
                        normalized_record[field] = None
            
            for field, dtype in numeric_float_fields.items():
                if field in normalized_record and normalized_record[field] is not None:
                    try:
                        normalized_record[field] = dtype(normalized_record[field])
                    except (ValueError, TypeError):
                        normalized_record[field] = None
            
            # Ensure boolean fields
            boolean_fields = ["goal_game_winner", "goal_empty_net"]
            for field in boolean_fields:
                if field in normalized_record:
                    val = normalized_record[field]
                    if isinstance(val, bool):
                        pass  # Already boolean
                    elif isinstance(val, (int, float)):
                        normalized_record[field] = bool(val)
                    else:
                        normalized_record[field] = False
            
            # Ensure string fields are properly formatted
            string_fields = ["event_type_code", "player_name_full", "team_name", "shot_type_desc"]
            for field in string_fields:
                if field in normalized_record and normalized_record[field] is not None:
                    normalized_record[field] = str(normalized_record[field]).strip()
            
            normalized_data.append(normalized_record)
        
        self.record_lineage(
            "data_normalized",
            metadata={"records_normalized": len(normalized_data)}
        )
        
        return normalized_data
    
    def fetch_data(self) -> pl.DataFrame:
        """
        Convenience method to fetch and process data in one call.
        
        Returns:
            polars.DataFrame with processed play-by-play event data
        """
        return self.run()
    
    @staticmethod
    def build_game_id(season: int, game_type: str = "02", game_number: int = 1) -> str:
        """
        Build an NHL game ID from components.
        
        Args:
            season: Starting year of season (e.g., 2024 for 2024-25)
            game_type: "02" for regular season, "03" for playoffs
            game_number: Game number (1-1312 for regular season)
            
        Returns:
            Game ID string (e.g., "2024020001")
        """
        return f"{season}{game_type}{game_number:04d}"
    
    @staticmethod
    def get_recent_game_id() -> str:
        """
        Get a recent NHL game ID for testing (from 2024-25 season).
        
        Returns:
            Game ID string
        """
        # Game from 2024-25 season (Oct 8, 2024: TOR @ MTL)
        return "2024020001"
