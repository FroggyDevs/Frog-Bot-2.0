"""


Frog Bot 2.0
Released Build
Beta 0.6
Updated May 11, 2022
Copyrighted by Jonathan Creado (HereJohnnyboi)



"""

import os
from keep_alive import keep_alive
import discord
from discord.ext import commands
import youtube_dl
from urllib import parse, request
import asyncio
import random
import functools
import itertools
from async_timeout import timeout
import math
from pretty_help import DefaultMenu, PrettyHelp
import requests
import json
import re
import praw
from datetime import datetime
from bs4 import BeautifulSoup
try:
  from googlesearch import search
except:
  os.system("pip install googlesearch-python")
  from googlesearch import search

intents= discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix=["f","F","frog ","froG ","frOg ","frOG ","fRog ","fRoG ","fROg ","fROG ","Frog ","FroG ","FrOg ","FrOG ","FRog ","FRoG ","FROg ","FROG "], case_insensitive=True, intents=intents)
client = bot
bot.author_id = 854898025893199913











def convertTuple(tup):
    str = ''
    for item in tup:
        str = str + " " + item
    return str
  
youtube_dl.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return ', '.join(duration)


class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=self.source.duration)
                 .add_field(name='Requested by', value=self.requester.mention)
                 .add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='URL', value='[Click]({0.source.url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(180):  # 3 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))

        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.add_field(name='Warning', value=message)
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please use the 'suggest' command or join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        await ctx.send(embed=embed)



    @commands.command(name='join', invoke_without_subcommand=True,case_insensitive = True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon',case_insensitive = True)
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.
        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError('You are neither connected to a voice channel nor specified a channel to join.')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', case_insensitive = True,aliases=['disconnect'])
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume',case_insensitive = True)
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        if 0 > volume > 100:
            return await ctx.send('Volume must be between 0 and 100')

        ctx.voice_state.volume = volume / 100
        await ctx.send('Volume of the player set to {}%'.format(volume))

    @commands.command(name='now', case_insensitive = True,aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""
        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(case_insensitive = True)
    async def pause(self, ctx):
        """Pauses currently playing song [Format: %pause]"""
        SongPlaying = ctx.voice_client.is_playing()
        Paused = ctx.voice_client.is_paused()
        if Paused != True:
            ctx.voice_client.pause()
            await ctx.message.add_reaction('⏯')
        else:
            if SongPlaying == True:
                await ctx.send("> The video player is already paused.")
            else:
                await ctx.send("> There is no song currently playing.")

    @commands.command(case_insensitive = True)
    async def resume(self, ctx):
        """Resumes a paused song [Format: %resume]"""
        Paused = ctx.voice_client.is_paused()
        if Paused == True:
            ctx.voice_client.resume()
            await ctx.message.add_reaction('⏯')
        else:
            await ctx.send('> The player is not paused')

    @commands.command(name='stop',case_insensitive = True)
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if not ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='skip',case_insensitive = True)
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """
        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 3:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send('Skip vote added, currently at **{}/3**'.format(total_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='queue',case_insensitive = True)
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle',case_insensitive = True)
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove',case_insensitive = True)
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop',case_insensitive = True)
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')

    @commands.command(name='play',case_insensitive = True)
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('An error occurred while processing this request: {}'.format(str(e)))
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send('Enqueued {}'.format(str(source)))

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('Bot is already in a voice channel.')

class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.add_field(name='Warning', value=message)
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please use the 'suggest' command or join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        await ctx.send(embed=embed)

    @commands.command(pass_context=True,case_insensitive = True, aliases = ["purge","clean"])
    @commands.has_permissions(manage_guild=True)
    async def clear(self, ctx, number):
        """Clears the chat of a specified number of messages."""
        await ctx.channel.purge(number=number)
        await ctx.send('Cleared by {}'.format(ctx.author.mention), delete_after=5)

    @commands.command(
        help="Shows the ping/latency of the bot in miliseconds.",
        brief="Shows ping.",
        case_insensitive = True,
        aliases = ["status"]
    )
    async def ping(self, ctx):
        if round(client.latency * 1000) <= 50:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0x44ff44)
        elif round(client.latency * 1000) <= 100:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0xffd000)
        elif round(client.latency * 1000) <= 200:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0xff6600)
        else:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0x990000)
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def print(self,ctx, *text):
        """Prints the specified value back to the channel."""
        await ctx.channel.send(convertTuple(text))

    @commands.command(case_insensitive = True)
    async def stream(self,ctx, *stream):
        """Changes what I am streaming."""
        await bot.change_presence(activity=discord.Streaming(name=convertTuple(stream), url="http://www.twitch.tv/accountname"))
        await ctx.message.add_reaction('✅')





    @commands.command(case_insensitive = True, aliases = ["server"])
    async def info(self, ctx):
        """Information about the server."""
        role_count = len(ctx.guild.roles)
        list_of_bots = [bot.mention for bot in ctx.guild.members if bot.bot]
        staff_roles = ["Froggy","Frog","Owner", "Head Dev", "Dev", "Head Admin", "Admins", "Moderators", "Community Helpers","Mod","Support","Members"]
        name = str(ctx.guild.name)
        description = str(ctx.guild.description)
        if description=="None":
          description = "No server description."
        embed2 = discord.Embed(title=name + " Server Information", description=description,timestamp=ctx.message.created_at, color=ctx.author.color)
        embed2.add_field(name='Name', value=f"{ctx.guild.name}", inline=True)
        embed2.add_field(name='Owner', value=str(client.get_user(int(ctx.guild.owner.id))), inline=True)
        embed2.add_field(name='Verification Level', value=str(ctx.guild.verification_level), inline=True)
        embed2.add_field(name='Highest role', value=ctx.guild.roles[0], inline=True)

        for r in staff_roles:
            role = discord.utils.get(ctx.guild.roles, name=r)
            if role:
                members = '\n'.join([member.name for member in role.members]) or "None"
                embed2.add_field(name=role.name, value=members)

        embed2.add_field(name='Number of roles', value=str(role_count), inline=True)
        embed2.add_field(name='Number Of Members', value=ctx.guild.member_count, inline=True)
        embed2.add_field(name='Bots:', value=(', '.join(list_of_bots)))
        embed2.add_field(name='Created At', value=ctx.guild.created_at.__format__('%A, %d. %B %Y @ %H:%M:%S'), inline=True)
        embed2.set_thumbnail(url=ctx.guild.icon_url)
        embed2.set_author(name=ctx.author.name, icon_url=ctx.author.avatar_url)
        embed2.set_footer(text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        await ctx.send(embed=embed2) 


    @commands.command(case_insensitive = True, aliases = ["youtube"])
    async def video(self, ctx, *, search):
        """Seacrches youtube for videos."""
        query_string = parse.urlencode({'search_query': search})
        html_content = request.urlopen('http://www.youtube.com/results?' + query_string)
        # print(html_content.read().decode())
        search_results = re.findall( r"watch\?v=(\S{11})", html_content.read().decode())
        print(search_results)
        await ctx.send('https://www.youtube.com/watch?v=' + search_results[0])

    
    @commands.command(case_insensitive = True, aliases = ["suggestion"])
    async def suggest(self,ctx, *suggestion):
      """Help me be better by suggesting!"""
      stuff = "\n" + str(ctx.message.author) + ": " + convertTuple(suggestion)
      f = open("suggestions.txt", "a")
      f.write(stuff)
      f.close()
      await ctx.message.add_reaction('✅')
      await ctx.send("Thank you for suggesting!")



    @commands.command(case_insensitive = True)
    @commands.has_guild_permissions(kick_members=True)
    async def kick(self,ctx, member: discord.Member, *, reason=None):
      """Kicks a user."""
      await member.kick(reason=reason)
      await ctx.message.add_reaction('✅')
      await ctx.send(f'{member.name} has been kicked for the reason of {reason}')

    @commands.command(case_insensitive = True)
    @commands.has_permissions(ban_members=True)
    async def ban(self,ctx, member: discord.Member, *, reason=None):
      """Bans a user."""
      await member.ban(reason=reason)
      await ctx.message.add_reaction('✅')
      await ctx.send(f'{member.name} has been banned for the reason of {reason}')

    @commands.command(pass_context=True,case_insensitive = True)
    @commands.has_permissions(manage_guild=True)
    async def role(self, ctx, user: discord.Member, role: discord.Role):
        """Gives a user a role."""
        await user.add_roles(role)
        await ctx.message.add_reaction('✅')
        await ctx.send(f"{user.name} has been giving a role called: {role.name}")
    
    @commands.command(case_insensitive = True, aliases = ["spam"])
    async def repeat(self, ctx, times: int, *content):
        """Repeats a message multiple times."""
        if times > 10:
          await ctx.send("You can only repeat things up to 10 times.")
        else: 
          for i in range(times):
            await ctx.send(convertTuple(content))
    
    @commands.command(case_insensitive = True)
    async def icon(self, ctx):
        """Links the server's icon."""
        icon_url = ctx.guild.icon_url
        await ctx.send(icon_url)

    @commands.command(case_insensitive = True)
    async def avatar(self, ctx, *,  avamember : discord.Member="test"):
        """Links the specified user's avatar."""
        if avamember == "test":
          await ctx.send(ctx.author.avatar_url)
        else:
          userAvatarUrl = avamember.avatar_url
          await ctx.send(userAvatarUrl)

    @commands.command(pass_context=True, aliases=["rr", "removerole"])
    @commands.has_permissions(manage_guild=True)
    async def roleremove(self, ctx, user: discord.Member, roleid):
      """Removes a role from a user."""
      asyncio.sleep(1)
      guild = ctx.message.guild
      role = guild.get_role(int(roleid))
      await user.remove_roles(role)
      await ctx.send(f"{user.name} has had a role taken from them.")


cointoss = ["heads","tails"]
shoot0 = [
  "rock",
  "paper",
  "scissors"
]

roll0 = [
  "1",
  "2",
  "3",
  "4",
  "5",
  "6"
]

class Math(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.add_field(name='Warning', value=message)
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please use the 'suggest' command or join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        await ctx.send(embed=embed)

      
    @commands.command(case_insensitive = True)
    async def add(self,ctx, first_number: int, second_number: int):
        """Adds two numbers together."""
        await ctx.send(first_number + second_number)

    @commands.command(case_insensitive = True)
    async def subtract(self,ctx, first_number: int, second_number: int):
        """Subtracts two numbers."""
        await ctx.send(first_number - second_number)

    @commands.command(case_insensitive = True)
    async def multiply(self,ctx, first_number: int, second_number: int):
        """Multiply two numbers."""
        await ctx.send(first_number * second_number)

    @commands.command(case_insensitive = True)
    async def divide(self,ctx, first_number: int, second_number: int):
        """Divides two numbers."""
        await ctx.send(first_number / second_number)

    @commands.command(case_insensitive = True, aliases = ["root","square root"])
    async def sqrt(self, ctx, number: int):
        '''Calculates the square root of a number.'''
        await ctx.send(math.sqrt(number))
      
    @commands.command(case_insensitive = True, aliases = ["tangent"])
    async def tan(self, ctx, number: int):
        '''Calculates the tangent of a number.'''
        await ctx.send(round(math.tan(math.radians(number)),2))

    @commands.command(case_insensitive = True, aliases = ["sine"])
    async def sin(self, ctx, number: int):
        '''Calculates the tangent of a number.'''
        await ctx.send(round(math.sin(math.radians(number)),2))

    @commands.command(case_insensitive = True, aliases = ["cosine"])
    async def cos(self, ctx, number: int):
        '''Calculates the tangent of a number.'''
        await ctx.send(round(math.cos(math.radians(number)),2))

  
    @commands.command(case_insensitive = True, aliases = ["radian","radians"])
    async def rad(self, ctx, number: int):
        '''Converts given number of degrees into radians.'''
        await ctx.send(math.radians(number))

    @commands.command(case_insensitive = True, aliases = ["degree","degrees"])
    async def deg(self, ctx, number: int):
        '''Converts given number of radians into degrees.'''
        await ctx.send(math.degrees(number))
      


def get_quote():
  response = requests.get("https://zenquotes.io/api/random")
  json_data = json.loads(response.text)
  quote = json_data[0]['q'] + " -" + json_data[0]['a']
  return(quote)

class Helpful(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.add_field(name='Warning', value=message)
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please use the 'suggest' command or join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def inspire(self,ctx):
        """Sends an inspirational quote."""
        embed = discord.Embed(title=f"{get_quote()}", color=discord.Color.blue())
        embed.set_footer(text=f"Quotes from zenquotes.io")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["flip","coin"])
    async def coinflip(self,ctx):
        """Flips a coin"""
        coin = random.choice(cointoss)
        if coin == "heads":
          embed = discord.Embed(title=f"Heads",color=discord.Color.blue())
          embed.set_thumbnail(url="https://m.media-amazon.com/images/I/51xs7F+tP5L._AC_.jpg")
          await ctx.send(embed=embed)
        else:
          embed = discord.Embed(title=f"Tails",color=discord.Color.blue())
          embed.set_thumbnail(url="https://m.media-amazon.com/images/I/51NyMaKLydL._AC_.jpg")
          await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["matoo","truth"])
    async def fax(self,ctx):
      """Fax"""
      await ctx.send("Matoo is sexy")


    @commands.command()
    async def rps(self,ctx,case_insensitive = True):
        """ROCK PAPER SCISSORS SHOOT!!!!"""
        shoot = random.choice(shoot0)
        if shoot == "rock":
          embed = discord.Embed(title=f"Rock",color=discord.Color.blue())
          embed.set_thumbnail(url="https://m.media-amazon.com/images/I/61m9jG+jj-L._AC_SY355_.jpg")
          await ctx.send(embed=embed)
        if shoot == "paper":
          embed = discord.Embed(title=f"Paper",color=discord.Color.blue())
          embed.set_thumbnail(url="https://cdn.pixabay.com/photo/2017/08/11/14/02/paper-2631126_1280.jpg")
          await ctx.send(embed=embed)
        if shoot == "scissors":
          embed = discord.Embed(title=f"Scissors",color=discord.Color.blue())
          embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/7/76/Pair_of_scissors_with_black_handle%2C_2015-06-07.jpg/1200px-Pair_of_scissors_with_black_handle%2C_2015-06-07.jpg")
          await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["roll"])
    async def dice(self,ctx):
        """Rolls a dice."""
        shoot = random.choice(roll0)
        if shoot == "1":
          embed = discord.Embed(color=discord.Color.blue())
          embed.set_thumbnail(url="https://w7.pngwing.com/pngs/604/326/png-transparent-dice-dice-1-image-file-formats-rectangle-dice-thumbnail.png")
          await ctx.send(embed=embed)
        if shoot == "2":
          embed = discord.Embed(color=discord.Color.blue())
          embed.set_thumbnail(url="http://www.clker.com/cliparts/a/Y/E/o/z/t/dice-2-md.png")
          await ctx.send(embed=embed)
        if shoot == "3":
          embed = discord.Embed(color=discord.Color.blue())
          embed.set_thumbnail(url="http://www.clipartsuggest.com/images/160/dice-3-clip-art-at-clker-com-vector-clip-art-online-royalty-free-UvzDUn-clipart.png")
          await ctx.send(embed=embed)
        if shoot == "4":
          embed = discord.Embed(color=discord.Color.blue())
          embed.set_thumbnail(url="https://cdn.pixabay.com/photo/2014/04/03/10/24/dice-310335_1280.png")
          await ctx.send(embed=embed)
        if shoot == "5":
          embed = discord.Embed(color=discord.Color.blue())
          embed.set_thumbnail(url="http://www.clker.com/cliparts/e/y/7/h/W/K/dice-5-hi.png")
          await ctx.send(embed=embed)
        if shoot == "6":
          embed = discord.Embed(color=discord.Color.blue())
          embed.set_thumbnail(url="http://www.clker.com/cliparts/l/6/4/3/K/H/dice-6-md.png")
          await ctx.send(embed=embed)


  
    @commands.command(case_insensitive = True, aliases = ["dictionary"])
    async def define(self,ctx, worddd=""):
        """Sends the definition of a word."""
        
        def show_origin(soup):
            try:
                origin = soup.find('span', {'unbox': 'wordorigin'})
                print('\nOrigin -> ', origin.text)
            except AttributeError:
               pass


        def show_definitions(soup):
            print()
            global senseList
            senseList = []
            senses = soup.find_all('li', class_='sense')
            for s in senses:
                definition = s.find('span', class_='def').text
                senseList.append(definition)
                
                # Examples
                #examples = s.find_all('ul', class_='examples')
                #for e in examples:
                #    for ex in e.find_all('li'):
                #        print('\t-', ex.text)


        word_to_search = worddd
        scrape_url = 'https://www.oxfordlearnersdictionaries.com/definition/english/' + word_to_search

        headers = {"User-Agent": ""}
        web_response = requests.get(scrape_url, headers=headers)

        if web_response.status_code == 200:
            soup = BeautifulSoup(web_response.text, 'html.parser')

            try:
#               show_origin(soup)
                show_definitions(soup)
                embed = discord.Embed(title=word_to_search, description=f"-{senseList[0]}", color=discord.Color.blue())
                embed.set_footer(text=f"Definitions from Oxford's Advanced Learner's Dictionary")
                await ctx.send(embed=embed)
            except AttributeError:
                embed = discord.Embed(title=word_to_search, description='Word not found!!', color=discord.Color.blue())
                await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title=word_to_search, description='Failed to get response...', color=discord.Color.blue())
            await ctx.send(embed=embed)

  
    @commands.command(case_insensitive = True, aliases = ["remind", "remindme", "remind_me", "timer"])
    async def reminder(self, ctx, time, *, reminder):
        """A reminder that pings you after the set time is over."""
        print(time)
        print(reminder)
        user = ctx.message.author
        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        seconds = 0
        if reminder is None:
            embed.add_field(name='Warning', value='Please specify what do you want me to remind you about.') # Error message
        if time.lower().endswith("d"):
            seconds += int(time[:-1]) * 60 * 60 * 24
            counter = f"{seconds // 60 // 60 // 24} days"
        if time.lower().endswith("h"):
            seconds += int(time[:-1]) * 60 * 60
            counter = f"{seconds // 60 // 60} hours"
        elif time.lower().endswith("m"):
            seconds += int(time[:-1]) * 60
            counter = f"{seconds // 60} minutes"
        elif time.lower().endswith("s"):
            seconds += int(time[:-1])
            counter = f"{seconds} seconds"
        if seconds == 0:
            embed.add_field(name='Warning',
                            value='Please specify a proper duration, send `reminder_help` for more information.')
        #elif seconds < 300:
        #    embed.add_field(name='Warning',
        #                value='You have specified a too short duration!\nMinimum duration is 5 minutes.')
        elif seconds > 7776000:
            embed.add_field(name='Warning', value='You have specified a too long duration!\nMaximum duration is 90 days.')
        else:
            await ctx.send(f"Alright, I will remind you about {reminder} in {counter}.")
            await asyncio.sleep(seconds-2)
            await ctx.send(f'Hi {user.mention}, you asked me to remind you about "{reminder}" {counter} ago.')
            return
        await ctx.send(embed=embed)


    @commands.command(case_insensitive = True, aliases = ["udictionary", "urban dictionary "])
    async def urban(self,ctx, *, udsearchq):
        """Searches definitions in the 'Urban Dictionary'."""
        try:
            uds = udsearchq.replace(" ", "%20")
            res = requests.get(f"https://udict-api.glique.repl.co/{uds}").json()
            auth = res["author"]
            defi = res["definition"]
            example = res["example"]
            url = res["permalink"]
            embed=discord.Embed(title=udsearchq, url=url, description='(Urban Dictionary Definition)', color=0x324e85)
            embed.add_field(name="Author:", value=auth, inline=False)
            embed.add_field(name="Definition:", value=defi, inline=False)
            embed.add_field(name="Example:", value=example, inline=False)
            embed.set_footer(text=f"Definitions from The Urban Dictionary")
            await ctx.send(embed=embed)
        except:
            embed=discord.Embed(title=udsearchq, description='Not Found', color=0x324e85)
            await ctx.send(embed=embed)







class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.add_field(name='Warning', value=message)
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please use the 'suggest' command or join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def lol(self,ctx):
        """Ha"""
        await ctx.send("HA")

    @commands.command(case_insensitive = True)
    async def lmao(self,ctx):
        """HAHA"""
        content="HAHA"
        for i in range(5):
            await ctx.send(content)

    @commands.command(case_insensitive = True)
    async def lmfao(self,ctx):
        """HAHAHAHAHAHAHAHA"""
        content="HAHA"
        for i in range(100):
            await ctx.send(content)
    
    @commands.command(case_insensitive = True)
    async def onigai(self,ctx):
        """ONI GAI"""
        embed = discord.Embed(title=f"**ONIGAI**",color=discord.Color.blue())
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def ribbit(self,ctx):
        """What do you expect, i'm a frog."""
        content="Ribbit"
        await ctx.message.add_reaction('🐸')
        for i in range(2):
            await ctx.send(content)

    @commands.command(case_insensitive = True)
    async def nou(self,ctx):
        """NO U!!!"""
        embed = discord.Embed(title=f"NO U",color=discord.Color.blue())
        embed.set_thumbnail(url="https://m.media-amazon.com/images/I/515EBaHdMoL._AC_SL1000_.jpg")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def notfunny(self,ctx):
        """Not funny."""
        embed = discord.Embed(title=f"No haha",color=discord.Color.blue())
        embed.set_thumbnail(url="https://c.tenor.com/BM-QtYCZIloAAAAM/not-funny-didnt-laugh.gif")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def gasp(self,ctx):
        """Gasp!"""
        embed = discord.Embed(title=f"*Gasp*",color=discord.Color.blue())
        embed.set_thumbnail(url="https://wp.wwu.edu/emmettpaige/files/2018/11/cropped-pika-2i0clzo.jpg")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def deez(self,ctx):
      """Hmmmm"""
      embed = discord.Embed(title=f"",color=discord.Color.blue())
      embed.set_thumbnail(url="https://pyxis.nymag.com/v1/imgs/a99/ea4/cc70e8f3fbc2b8c891d33b6f0b7bcab837-23-deez-nuts-lg.2x.h473.w710.jpg")
      await ctx.send(embed=embed)




reddit = praw.Reddit(client_id='Cm7end5jxX5qTbtAbb92xA', client_secret='UPG8USyN1uml4SZpVRQBZSgDxtYCeQ', user_agent='Frog_Bot', check_for_async=False)

class Reddit(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        embed = discord.Embed(color=0x55a7f7, timestamp=datetime.utcnow())
        embed.add_field(name='Warning', value=message)
        embed.set_footer(text="If you have any questions, suggestions or bug reports, please use the 'suggest' command or join our support Discord Server: link hidden", icon_url=f"{client.user.avatar_url}")
        await ctx.send(embed=embed)


    @commands.command(case_insensitive = True, aliases = ["funny"])
    async def joke(self, ctx):
      """Sends a life pro tip from r/dadjokes."""
      subreddit = reddit.subreddit("dadjokes")
      all_subs = []
      hot = subreddit.hot(limit = 100)
      for submission in hot:
          all_subs.append(submission)
      random_sub = random.choice(all_subs)
      name = random_sub.title
      desc = random_sub.selftext
      embed = discord.Embed(title = name, description=desc, color=discord.Color.green())
      embed.set_footer(text=f"Asked by {ctx.author.name}")
      await ctx.send(embed=embed)

    @commands.command(case_insensitive = True )
    async def news(self, ctx):
      """Sends news from r/worldnews."""
      subreddit = reddit.subreddit("worldnews")
      all_subs = []
      hot = subreddit.hot(limit = 100)
      for submission in hot:
          all_subs.append(submission)
      random_sub = random.choice(all_subs)
      name = random_sub.title
      desc = random_sub.selftext
      embed = discord.Embed(title = name, description=desc, color=discord.Color.green())
      embed.set_footer(text=f"Asked by {ctx.author.name}")
      await ctx.send(embed=embed)
    

    @commands.command(case_insensitive = True, aliases = ["life pro tip","tip","advice"])
    async def lpt(self, ctx):
      """Sends a life pro tip from r/LifeProTips."""
      subreddit = reddit.subreddit("LifeProTips")
      all_subs = []
      hot = subreddit.hot(limit = 100)
      for submission in hot:
          all_subs.append(submission)
      random_sub = random.choice(all_subs)
      name = random_sub.title
      desc = random_sub.selftext
      embed = discord.Embed(title = name, description=desc, color=discord.Color.green())
      embed.set_footer(text=f"Asked by {ctx.author.name}")
      await ctx.send(embed=embed)


    @commands.command(case_insensitive = True)
    async def meme(self, ctx):
        """Sends a meme from r/memes."""
        subreddit = reddit.subreddit("memes")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)
  
    @commands.command(case_insensitive = True, aliases = ["cool guide"])
    async def guide(self, ctx):
        """Sends a cool guide from r/coolguides."""
        subreddit = reddit.subreddit("coolguides")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["picture","photo"])
    async def pic(self, ctx):
        """Sends a cool picture from r/pics."""
        subreddit = reddit.subreddit("pics")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["food porn","yummy"])
    async def food(self, ctx):
        """Sends a picture of food from r/food."""
        subreddit = reddit.subreddit("food")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["universe","sun","moon"])
    async def space(self, ctx):
        """Sends a picture of space from r/spaceporn."""
        subreddit = reddit.subreddit("spaceporn")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True)
    async def greentext(self, ctx):
        """Sends a 4chan story from r/greentext."""
        subreddit = reddit.subreddit("greentext")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["doggy","puppy"])
    async def dog(self, ctx):
        """Sends a cute dog pic from r/dogpictures."""
        subreddit = reddit.subreddit("dogpictures")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive = True, aliases = ["kitty", "kitten"])
    async def cat(self, ctx):
        """Sends a cute cat pic from r/catpics."""
        subreddit = reddit.subreddit("catpics")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)


    @commands.command(case_insensitive = True)
    async def earth(self, ctx):
        """Sends a picture from r/earthporn."""
        subreddit = reddit.subreddit("EarthPorn")
        all_subs = []
        hot = subreddit.hot(limit = 100)
        for submission in hot:
            all_subs.append(submission)
        random_sub = random.choice(all_subs)
        name = random_sub.title
        url = random_sub.url
        embed = discord.Embed(title = name, color=discord.Color.green())
        embed.set_image(url = url)
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        await ctx.send(embed=embed)

        
menu = DefaultMenu('◀️', '▶️', '❌') # You can copy-paste any icons you want.
bot.help_command = PrettyHelp(navigation=menu, color=discord.Colour.green())


keep_alive()
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Streaming(name="frog help", url="http://www.twitch.tv/accountname"))




client.add_cog(Utility(client))
client.add_cog(Music(client))
client.add_cog(Math(client))
client.add_cog(Helpful(client))
client.add_cog(Social(client))
client.add_cog(Reddit(client))
oldToken = os.environ['oldToken']
token = os.environ['token']
client.run(oldToken)


