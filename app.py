#!/usr/bin/env python3

import pprint
pp = pprint.PrettyPrinter(indent=4)

import math
import os
import psycopg2
import re
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

MAX_NUM_CHOICES = 30

DATABASE_URL = os.environ['DATABASE_URL']

# Initializes the app
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# Create the database connection (psycopg2 connections are thread-safe)
con = psycopg2.connect(DATABASE_URL, sslmode='require')

# Create the necessary tables in the sqlite database
with con:
    with con.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY,
            channel_id TEXT NOT NULL,
            message_ts TEXT NOT NULL,
            anonymous INTEGER NOT NULL,
            allow_multiple INTEGER NOT NULL,
            UNIQUE(channel_id, message_ts)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS choices (
            id INTEGER PRIMARY KEY,
            poll_id INTEGER NOT NULL,
            action_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            UNIQUE(poll_id, action_id),
            FOREIGN KEY (poll_id) REFERENCES polls (id)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            choice_id INTEGER NOT NULL,
            UNIQUE(user_id, choice_id),
            FOREIGN KEY (choice_id) REFERENCES choices (id)
        )''')

@app.command("/pollcenta")
@app.shortcut("pollcenta")
def pollcenta_command(ack, body, client):
    ack()
    if 'channel_id' in body:
        channel_id = body['channel_id']
        conversation_selct_blocks = []
    else:
        channel_id = 'none'
        conversation_selct_blocks = [{
            "type": "input",
            "block_id": "channel_select",
            "label": {
                "type": "plain_text",
                "text": "What channel should the poll be posted to?"
            },
            "element": {
                "type": "conversations_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Channel"
                },
                "action_id": "channel_select",
                "default_to_current_conversation": True
            }
        }]
    base_view = {
        "type": "modal",
        "callback_id": "poll_creator",
        "title": {
            "type": "plain_text",
           "text": "Create a poll"
        },
        "submit": {
            "type": "plain_text",
            "text": "Submit"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "blocks": [
            {
                "type": "input",
                "block_id": "basics",
                "optional": True,
                "label": {
                    "type": "plain_text",
                    "text": "Enable any basic poll settings"
                },
                "element": {
                    "type": "checkboxes",
                    "action_id": "basic_values",
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Make this poll anonymous"
                            },
                            "value": "anonymous"
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Allow users to select multiple options"
                            },
                            "value": "multiselect"
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Allow users to add their own options"
                            },
                            "value": "addoptions"
                        }
                    ]
                }
            },
            {
                "type": "input",
                "block_id": "poll",
                "optional": False, # User must provide a topic
                "label": {
                    "type": "plain_text",
                    "text": "Poll question"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "poll"
                }
            },
            {
                "type": "divider",
                "block_id": channel_id # Shove the channel ID into this field so we can get it when responding
            },
            {
                "type": "input",
                "block_id": "choice_1",
                "optional": False, # User must provide at least two options
                "label": {
                    "type": "plain_text",
                    "text": "Choice 1"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "choice",
                    "max_length": 75
                }
            },
            {
                "type": "input",
                "block_id": "choice_2",
                "optional": False, # User must provide at least two options
                "label": {
                    "type": "plain_text",
                    "text": "Choice 2"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "choice",
                    "max_length": 75
                }
            },
            {
                "type": "input",
                "block_id": "choice_3",
                "optional": True,
                "label": {
                    "type": "plain_text",
                    "text": "Choice 3"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "choice",
                    "max_length": 75
                }
            },
            {
                "type": "input",
                "block_id": "choice_4",
                "optional": True,
                "label": {
                    "type": "plain_text",
                    "text": "Choice 4"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "choice",
                    "max_length": 75
                }
            },
            {
                "type": "section",
                "text": {
                    "text": "*4 / {} choices used*".format(MAX_NUM_CHOICES),
                    "type": "mrkdwn"
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "➕ Add More Choices"
                    },
                    "action_id": "addchoices"
                }
            },
            *conversation_selct_blocks
        ]
    }

    client.views_open(
        trigger_id=body["trigger_id"],
        view=base_view
    )

@app.view("poll_creator")
def handle_poll_creation(ack, body, client, view):
    ack()
    values = view['state']['values']

    # Get the channel ID we hid in the divider's block ID
    channel_id = view['blocks'][2]['block_id']

    # If this was initiated with a shortcut, then the channel ID is passed in a different way
    if channel_id == 'none':
        channel_id = values['channel_select']['channel_select']['selected_conversation']

    # Get the basic options the user set
    basic_options = list(map(lambda x: x['value'], values['basics']['basic_values']['selected_options']))

    # Get the poll topic
    prompt = values['poll']['poll']['value']
    topic = '*{}*'.format(prompt)
    if 'multiselect' in basic_options:
        topic += '\nYou may vote for multiple options'
    head_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": topic
        }
    }

    # Get the choices the user provided
    choices = []
    for i in range(30):
        action_id = 'choice_{}'.format(i + 1)
        if action_id in values:
            content = values[action_id]['choice']['value']
            if content is not None:
                choices.append((action_id, content))

    # If users should be able to add options to the poll, add a button for this
    if 'addoptions' in basic_options:
        choices.append(('add_user_choice', '➕ Add an option'))
    
    # Build the buttons for users to respond with
    action_blocks = []
    for index, (action_id, content) in enumerate(choices):
        if index % 5 == 0:
            action_blocks.append({
                "type": "actions",
                "elements": []
            })
        action_blocks[-1]['elements'].append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "{}".format(content)
            },
            "action_id": action_id
        })

    # Get the poster's name
    poster = client.users_info(user=body['user']['id'])
    poster_name = '???'
    if poster['ok']:
        poster_name = poster['user']['real_name']
    # Get whether the poll is anonymous
    anonymity_icon = '🔓 '
    anonymity_string = 'Non-Anonymous'
    if 'anonymous' in basic_options:
        anonymity_icon = '🔒'
        anonymity_string = 'Anonymous'
    context_block = {
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "Sender: {} | {} *Responses:* {}".format(poster_name, anonymity_icon, anonymity_string)
        }]
    }

    # Post the poll
    client.chat_postMessage(
        channel=channel_id,
        text=prompt,
        blocks=[head_block, *action_blocks, context_block]
    )

    # TODO It would be great if we could add the message to the polls table here

@app.action("addchoices")
def handle_add_choices(ack, body, client):
    ack()
    # Get the old view
    old_view = body['view']
    # Build a new view from the relevant components of the old view
    new_view = {
        'type': old_view['type'],
        'callback_id': old_view['callback_id'],
        'title': old_view['title'],
        'submit': old_view['submit'],
        'close': old_view['close'],
        'blocks': old_view['blocks']
    }
    # Count the number of choices that already were present
    next_choice_num = len([block for block in new_view['blocks'] if block['block_id'].startswith('choice_')]) + 1
    # Add a new choice to the end of the choices
    new_view['blocks'].insert(-1, {
        "type": "input",
        "block_id": "choice_{}".format(next_choice_num),
        "optional": True,
        "label": {
            "type": "plain_text",
            "text": "Choice {}".format(next_choice_num)
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "choice",
            "max_length": 75
        }
    })

    if next_choice_num < MAX_NUM_CHOICES:
        # Increment the count of choices available
        new_view['blocks'][-1]['text']['text'] = "*{} / {} choices used*".format(next_choice_num, MAX_NUM_CHOICES)
    else:
        # No more choices can be added
        del new_view['blocks'][-1]

    # Update the view
    client.views_update(
        view_id=body["view"]["id"],
        hash=body["view"]["hash"],
        view=new_view
    )

@app.action(re.compile("choice_\d+"))
def handle_make_choice(ack, body, respond):
    ack()
    # Get the existing blocks
    blocks = body['message']['blocks']
    # Extract out the header, action buttons, and context
    header_block = blocks[0]
    action_blocks = [block for block in blocks if block['type'] == 'actions']
    context_block = blocks[-1]

    # Get the channel and message IDs
    channel_id = body['container']['channel_id']
    message_ts = body['container']['message_ts']

    # Check if the message is anonymous or multi-select
    anonymous = context_block['elements'][0]['text'].endswith(' | :lock: *Responses:* Anonymous')
    allow_multiple = header_block['text']['text'].endswith('*\nYou may vote for multiple options')

    # Get the action button that was clicked
    action_id = int(body['actions'][0]['action_id'].split('_')[1])

    # Get the user who responded
    user_id = body['user']['id']

    # Handle the database interactions
    with con:
        with con.cursor() as cur:
            # Insert an entry for this poll into the database if it isn't already present
            cur.execute('''INSERT INTO polls(channel_id, message_ts, anonymous, allow_multiple)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT DO NOTHING
                        ''',
                        (channel_id, message_ts, anonymous, allow_multiple))

            # Get the poll ID
            poll_id = cur.execute('SELECT id FROM polls WHERE channel_id = %s AND message_ts = %s', (channel_id, message_ts)).fetchone()[0]

            # Insert entries for all the choices if they aren't already present
            for action_block in action_blocks:
                for action in action_block['elements']:
                    if re.match("choice_\d+", action['action_id']):
                        cur.execute('''INSERT INTO choices(poll_id, action_id, content)
                                       VALUES (%s, %s, %s)
                                       ON CONFLICT DO NOTHING
                                    ''',
                                    (poll_id, int(action['action_id'].split('_')[1]), action['text']['text']))

            # Check if this user has already chosen the selected response
            resp = cur.execute('''SELECT responses.id
                                  FROM responses
                                  INNER JOIN choices
                                  ON responses.choice_id=choices.id
                                  WHERE responses.user_id = %s
                                  AND choices.poll_id = %s
                                  AND choices.action_id = %s
                               ''', (user_id, poll_id, action_id)).fetchone()
            if resp is None:
                # If multiple responses are not allowed, delete any old ones from this user
                if not allow_multiple:
                    cur.execute('''DELETE FROM responses
                                   WHERE id IN (
                                       SELECT responses.id
                                       FROM responses
                                       INNER JOIN choices
                                       ON responses.choice_id=choices.id
                                       WHERE choices.poll_id = %s
                                       AND responses.user_id = %s
                                   )
                                ''', (poll_id, user_id))
                # Insert an entry for this response
                cur.execute('''INSERT INTO responses(user_id, choice_id)
                               SELECT %s, choices.id
                               FROM choices
                               WHERE poll_id = %s
                               AND action_id = %s
                            ''', (user_id, poll_id, action_id))
            else:
                # Delete the entry for this response
                cur.execute('DELETE FROM responses WHERE id = %s', (resp[0],))

            # Get all the choices and the people who have made them
            choices = cur.execute('''SELECT choices.content, responses.user_id
                                     FROM choices
                                     LEFT JOIN responses
                                     ON choices.id=responses.choice_id
                                     WHERE choices.poll_id = %s
                                     ORDER BY choices.action_id
                                  ''', (poll_id,)).fetchall()

    # Get the choice names
    choice_names = dict.fromkeys(choice[0] for choice in choices)

    # Count the number of total respondents (this avoids stupid percentages in the multi-select case)
    num_total_respondents = len(set(choice[1] for choice in choices if choice[1] is not None))

    # Build the new results blocks
    results_blocks = []
    if num_total_respondents != 0:
        for index, choice_name in enumerate(choice_names):
            # A section can only hold 10 items, so we might need multiple sections
            if index % 10 == 0:
                results_blocks.append({
                    "type": "section",
                    "fields": []
                })

            # See who responded with this choice
            respondents = [choice[1] for choice in choices if choice[0] == choice_name and choice[1] is not None]
            num_respondents = len(respondents)

            # Calculate the (rounded) percentage who chose this answer (as one of their answers in the multi-select case)
            percentage = round(num_respondents / num_total_respondents * 100)

            # Build a nice percentage bar in increments of 5%
            count_of_20 = math.ceil(percentage / 5)
            percentage_bar = '`' + ('\u2588' * count_of_20) + (' \u2062' * (20 - count_of_20)) + '`'

            respondents_str = ''
            if not anonymous:
                respondents_str = '\n' + ', '.join('<@{}>'.format(respondent) for respondent in respondents)

            # Build the actual response
            results_blocks[-1]['fields'].append({
                "type": "mrkdwn",
                "text": "{}\n{} | {}% ({}){}".format(choice_name, percentage_bar, percentage, num_respondents, respondents_str)
            })

    # Update the message to include the new results
    respond(
        replace_original=True,
        blocks=[header_block, *action_blocks, *results_blocks, context_block]
    )

@app.action("add_user_choice")
def handle_add_user_choice(ack, body, client):
    ack()
    base_view = {
        "type": "modal",
        "callback_id": "user_choice_added",
        "title": {
            "type": "plain_text",
            "text": "Add a choice"
        },
        "submit": {
            "type": "plain_text",
            "text": "Submit"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "blocks": [
            {
                "type": "input",
                "block_id": body['container']['channel_id'],
                "optional": False, # User must provide a choice
                "label": {
                    "type": "plain_text",
                    "text": "Choice to add to the poll"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": body['container']['message_ts'],
                    "max_length": 75
                }
            }
        ]
    }

    client.views_open(
        trigger_id=body["trigger_id"],
        view=base_view
    )

@app.view("user_choice_added")
def handle_user_choice_added(ack, body, client, respond, view):
    ack()
    values = view['state']['values']
    # We take advantage of the block_id and action_id fields in the block to pass through the channel_id and message_ts
    # There is almost certainly a better way to do this, but it works
    channel_id = view['blocks'][0]['block_id']
    message_ts = view['blocks'][0]['element']['action_id']

    # Get the value to add to the choices
    new_choice = values[channel_id][message_ts]['value']

    # Look up the message as it was previously sent
    results = client.conversations_history(
        channel=channel_id,
        oldest=message_ts,
        inclusive=True,
        limit=1
    )

    # Get the blocks of the message
    message = results['messages'][0]
    blocks = message['blocks']

    # Get the last action block from the list of blocks
    last_action_block_index = [index for (index, block) in enumerate(blocks) if block['type'] == 'actions'][-1]
    last_action_block = blocks[last_action_block_index]

    # Get the last action that was actually a choice (not the "Add an option" button)
    if len(last_action_block['elements']) > 1:
        last_choice_action = last_action_block['elements'][-2]
    else:
        last_choice_action = [block for block in blocks if block['type'] == 'actions'][-2]['elements'][-1]

    # Get the index of the last choice action_id
    last_choice_index = int(last_choice_action['action_id'].split('_')[1])

    # Replace the former "Add an option" button with the new choice
    last_action_block['elements'][-1]['text']['text'] = new_choice
    last_action_block['elements'][-1]['action_id'] = 'choice_{}'.format(last_choice_index + 1)

    # If we aren't at the limit, put the "Add an option" button back
    if last_choice_index < MAX_NUM_CHOICES - 1:
        # See if there is space in the current last block or if we need to add another
        if len(last_action_block['elements']) == 5:
            last_action_block = {
                "type": "actions",
                "elements": []
            }
            blocks.insert(last_action_block_index + 1, last_action_block)

        # Add the "Add an option" button back at the end of the last block
        last_action_block['elements'].append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": '➕ Add an option'
            },
            "action_id": 'add_user_choice'
        })

    # Edit the message to have the new option added
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=blocks,
        text=message['text'],
        as_user=True
    )

# Start the app as a socket mode handler
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()

