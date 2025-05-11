# Gmail Rule Processor

This Python project allows you to integrate with Gmail API and perform rule-based operations on emails. It fetches emails from your Gmail inbox, stores them in a local database, and processes them according to customizable rules.

## Features

- Authenticates with Google's Gmail API using OAuth
- Fetches emails from your Gmail inbox
- Stores emails in a SQLite database (easily configurable for other databases)
- Processes emails based on customizable rules stored in a JSON file
- Supports multiple conditions and actions per rule
- Supports rule predicates (ANY, ALL) for complex filtering
- Provides unit tests for all major components

## Requirements

- Python 3.7 or higher
- Google account with Gmail
- Google Cloud Platform project with Gmail API enabled

## Installation

1. Clone this repository or download the source code.

```bash
git clone https://github.com/yourusername/gmail-rule-processor.git
cd gmail-rule-processor
```

2. Install the required dependencies.

```bash
pip install -r requirements.txt
```

3. Create a Google Cloud Platform project and enable the Gmail API.
   - Go to the [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the Gmail API for your project
   - Create OAuth credentials (OAuth client ID)
   - Download the credentials as JSON and save as `client_secrets.json` in the project root

## Configuration

1. The rules for processing emails are stored in `email_rules.json`. A default version will be created automatically if the file doesn't exist. You can modify this file to add your own rules.

2. Each rule consists of:
   - A unique ID
   - A descriptive name
   - A predicate (ANY or ALL) that determines how conditions are combined
   - A list of conditions that determine when the rule applies
   - A list of actions to perform when the rule matches

Example rule:

```json
{
  "id": "rule1",
  "name": "Mark newsletters as read",
  "predicate": "any",
  "conditions": [
    {
      "field": "from",
      "predicate": "contains",
      "value": "newsletter"
    },
    {
      "field": "subject",
      "predicate": "contains",
      "value": "newsletter"
    }
  ],
  "actions": [
    {
      "type": "mark_as_read",
      "value": true
    }
  ]
}
```

## Usage

Run the main script:

```bash
python gmail_rule_processor.py
```

The script will guide you through the following options:
1. Fetch new emails from Gmail
2. Process existing emails with rules
3. Both fetch and process
4. Exit

The first time you run the script, it will open a browser window for you to authenticate with your Google account and grant permission to access your Gmail.

## Supported Fields, Predicates, and Actions

### Fields:
- From (sender email)
- To (recipient email)
- Subject (email subject)
- Message (email body content)
- Received (email received date/time)

### Predicates:
- For string type fields:
  - Contains
  - Does not Contain
  - Equals
  - Does not Equal
- For date type field (Received):
  - Less than (newer than X days/months)
  - Greater than (older than X days/months)

### Actions:
- Mark as read
- Mark as unread
- Move message (to another label/folder)

## Database Schema

The project uses SQLite by default, with the following schema:

### Table: emails
- id (TEXT, PRIMARY KEY): Email ID from Gmail
- thread_id (TEXT): Thread ID for conversation tracking
- subject (TEXT): Email subject
- sender (TEXT): Email sender
- recipient (TEXT): Email recipient
- received_date (TEXT): Original date string
- parsed_date (TEXT): ISO format date for easier processing
- snippet (TEXT): Email snippet
- body (TEXT): Email body content
- is_read (BOOLEAN): Read/unread status
- labels (TEXT): Comma-separated list of Gmail labels
- created_at (TIMESTAMP): When the email was added to the database

### Table: rule_actions
- id (INTEGER, PRIMARY KEY): Auto-increment ID
- email_id (TEXT): Foreign key to emails table
- rule_id (TEXT): Rule ID that was applied
- action_type (TEXT): Type of action applied
- action_value (TEXT): Value of the action
- applied_at (TIMESTAMP): When the action was applied

## Testing

Run the unit tests with:

```bash
python -m unittest test_gmail_rule_processor.py
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.