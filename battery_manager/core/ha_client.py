#!/usr/bin/env python3
"""
Home Assistant API Client

Liest Sensordaten aus Home Assistant (Tibber, Forecast.Solar, Battery SOC, etc.)
"""

import os
import requests
import logging

logger = logging.getLogger(__name__)


class HomeAssistantClient:
    """Client for Home Assistant Supervisor API"""
    
    def __init__(self):
        """Initialize Home Assistant API client"""
        self.token = os.getenv('SUPERVISOR_TOKEN')
        self.api_url = os.getenv('HASSIO_API', 'http://supervisor/core')
        
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        if not self.token:
            logger.warning("No SUPERVISOR_TOKEN found - running in development mode")
        else:
            logger.info("Home Assistant API client initialized")
    
    def get_state(self, entity_id):
        """
        Get state of an entity
        
        Args:
            entity_id: Entity ID (e.g., 'sensor.battery_soc')
        
        Returns:
            str: State value or None if failed
        """
        if not self.token:
            logger.debug(f"Cannot get state for {entity_id} - no token")
            return None
        
        try:
            url = f"{self.api_url}/api/states/{entity_id}"
            response = requests.get(url, headers=self.headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('state')
            else:
                logger.warning(f"Failed to get state for {entity_id}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting state for {entity_id}: {e}")
            return None
    
    def get_attributes(self, entity_id):
        """
        Get all attributes of an entity
        
        Args:
            entity_id: Entity ID
        
        Returns:
            dict: Attributes or None if failed
        """
        if not self.token:
            return None
        
        try:
            url = f"{self.api_url}/api/states/{entity_id}"
            response = requests.get(url, headers=self.headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('attributes', {})
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error getting attributes for {entity_id}: {e}")
            return None
    
    def call_service(self, domain, service, entity_id=None, data=None):
        """
        Call a Home Assistant service

        Args:
            domain: Service domain (e.g., 'light', 'switch')
            service: Service name (e.g., 'turn_on', 'turn_off')
            entity_id: Entity ID (optional)
            data: Additional service data (optional)

        Returns:
            bool: True if successful
        """
        if not self.token:
            logger.debug("Cannot call service - no token")
            return False

        try:
            url = f"{self.api_url}/api/services/{domain}/{service}"

            payload = data or {}
            if entity_id:
                payload['entity_id'] = entity_id

            response = requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=10
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"Error calling service {domain}.{service}: {e}")
            return False

    def get_state_with_attributes(self, entity_id):
        """
        Get entity state with all attributes (v0.2.1)

        Args:
            entity_id: Entity ID

        Returns:
            dict: Full entity data including state and attributes, or None if failed
        """
        if not self.token:
            logger.debug(f"Cannot get state with attributes for {entity_id} - no token")
            return None

        try:
            url = f"{self.api_url}/api/states/{entity_id}"
            response = requests.get(url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to get state with attributes for {entity_id}: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting state with attributes for {entity_id}: {e}")
            return None
