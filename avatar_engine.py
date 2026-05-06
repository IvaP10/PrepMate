class AudioOnlyAvatar:

    @property
    def available(self) -> bool:
        return True

    async def create_session(self):
        return None

    async def start_session(self, sdp_answer):
        return False

    async def send_audio_for_lipsync(self, audio_b64):
        pass

    async def send_text_for_speech(self, text):
        pass

    async def interrupt(self):
        pass

    async def send_ice_candidate(self, candidate):
        pass

    async def close(self):
        pass
