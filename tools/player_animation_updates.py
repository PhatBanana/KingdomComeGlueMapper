"""Keep the playable character's facial queues advancing off screen."""

MARKER = b'GluePlayerAnimationUpdates'
HOOK = b'''
-- GluePlayerAnimationUpdates: the player can enqueue facial locomotion clips
-- while its first-person body is culled. Mark the character, not the currently
-- queued animations (ForceCharacterUpdate), so new sprint/idle clips advance.
if not Player.GluePlayerAnimationUpdates then
    Player.GluePlayerAnimationUpdates = true
    local unpackValues = unpack or table.unpack
    local function pack(...) return {n=select('#', ...), ...} end
    local function enable(self)
        if self.CharacterUpdateAlways then
            self:CharacterUpdateAlways(0, true)
        end
    end
    local function wrap(name)
        local original = Player[name]
        if original then
            Player[name] = function(self, ...)
                local result = pack(original(self, ...))
                enable(self)
                return unpackValues(result, 1, result.n)
            end
        end
    end
    -- Player class only: NPC classes retain native animation culling.
    -- Model replacement creates a new character and loses its instance flags.
    wrap('SetActorModel')
    wrap('OnInit')
    wrap('OnReset')
    wrap('OnLoadAI')
end
'''


def patch_player(blob):
    """Append once to the complete native player script, retaining other hooks."""
    if MARKER in blob:
        return blob
    if b'function Player:OnInit()' not in blob or b'function Player:OnLoadAI(' not in blob:
        raise ValueError('Expected complete native Player lifecycle script')
    return blob + HOOK
