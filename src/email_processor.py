import json
import datetime
from dateutil import parser

# Import functions from the email_fetcher module
from email_fetcher import (
    get_gmail_service, fetch_emails_from_db, modify_labels,
    get_or_create_label, record_rule_action
)

# Path to rules file
RULES_FILE = 'email_rules.json'

def load_rules():
    """Load email processing rules from JSON file."""
    try:
        with open(RULES_FILE, 'r') as file:
            rules = json.load(file)
        return rules
    except FileNotFoundError:
        print(f"Rules file not found: {RULES_FILE}")
        # Create a default rules file with example
        default_rules = {
            "rules": [
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
                            "value": True
                        }
                    ]
                }
            ]
        }
        with open(RULES_FILE, 'w') as file:
            json.dump(default_rules, file, indent=2)
        print(f"Created default rules file: {RULES_FILE}")
        return default_rules
    except json.JSONDecodeError as e:
        print(f"Error parsing rules file: {e}")
        return {"rules": []}

def evaluate_condition(email, condition):
    """Evaluate a single condition against an email."""
    field = condition['field'].lower()
    predicate = condition['predicate'].lower()
    value = condition['value']
    
    if field == 'from':
        field_value = email['sender']
    elif field == 'to':
        field_value = email['recipient']
    elif field == 'subject':
        field_value = email['subject']
    elif field == 'message':
        field_value = email['body']
    elif field == 'received':
        # For date fields, we need special handling
        try:
            if not email['parsed_date']:
                return False
                
            email_date = parser.parse(email['parsed_date'])
            
            # Value should be in format like "5 days" or "2 months"
            parts = value.split()
            if len(parts) != 2:
                return False
                
            amount = int(parts[0])
            unit = parts[1].lower()
            
            now = datetime.datetime.now(email_date.tzinfo)
            
            if predicate == 'greater than':
                # Email is older than the specified time
                if unit.startswith('day'):
                    threshold = now - datetime.timedelta(days=amount)
                    return email_date < threshold
                elif unit.startswith('month'):
                    # Approximate months as 30 days for simplicity
                    threshold = now - datetime.timedelta(days=amount*30)
                    return email_date < threshold
            
            elif predicate == 'less than':
                # Email is newer than the specified time
                if unit.startswith('day'):
                    threshold = now - datetime.timedelta(days=amount)
                    return email_date > threshold
                elif unit.startswith('month'):
                    # Approximate months as 30 days for simplicity
                    threshold = now - datetime.timedelta(days=amount*30)
                    return email_date > threshold
                    
            return False
        except Exception as e:
            print(f"Error processing date condition: {e}")
            return False
    else:
        # Unknown field
        return False
    
    # String comparisons
    if predicate == 'contains':
        return value.lower() in field_value.lower()
    elif predicate == 'does not contain':
        return value.lower() not in field_value.lower()
    elif predicate == 'equals':
        return value.lower() == field_value.lower()
    elif predicate == 'does not equal':
        return value.lower() != field_value.lower()
    
    # If we got here, we don't know how to evaluate this predicate
    return False

def evaluate_rule(email, rule):
    """Evaluate all conditions in a rule against an email."""
    predicate = rule.get('predicate', 'all').lower()
    conditions = rule.get('conditions', [])
    
    if not conditions:
        return False
    
    results = [evaluate_condition(email, condition) for condition in conditions]
    
    if predicate == 'all':
        return all(results)
    elif predicate == 'any':
        return any(results)
    
    # Default to requiring all conditions
    return all(results)

def apply_action(service, email, action):
    """Apply a single action to an email."""
    action_type = action['type'].lower()
    value = action.get('value')
    
    if action_type == 'mark_as_read':
        if value is True:
            # Mark as read by removing UNREAD label
            modify_labels(service, email['id'], {'removeLabelIds': ['UNREAD']})
            return "marked as read"
        else:
            # Mark as unread by adding UNREAD label
            modify_labels(service, email['id'], {'addLabelIds': ['UNREAD']})
            return "marked as unread"
    
    elif action_type == 'move_message':
        # Value should be a label name like "INBOX" or "TRASH"
        # First, get the label ID if it's a user-defined label
        if value not in ['INBOX', 'TRASH', 'SPAM']:
            label_id = get_or_create_label(service, value)
        else:
            label_id = value
            
        if label_id:
            # Remove from current location and add to new location
            modify_labels(service, email['id'], {
                'removeLabelIds': ['INBOX'],  # Remove from inbox
                'addLabelIds': [label_id]     # Add to new location
            })
            return f"moved to {value}"
    
    return "action not supported"

def process_emails_with_rules(service):
    """Process emails in the database according to the rules."""
    # Load rules
    rules_data = load_rules()
    rules = rules_data.get('rules', [])
    
    if not rules:
        print("No rules found to process.")
        return 0
    
    # Fetch emails from the database
    emails = fetch_emails_from_db(limit=100)  # Process up to 100 emails
    
    if not emails:
        print("No emails found in the database to process.")
        return 0
    
    actions_applied = 0
    
    print(f"Processing {len(emails)} emails with {len(rules)} rules...")
    
    for email in emails:
        for rule in rules:
            rule_id = rule.get('id', 'unknown')
            rule_name = rule.get('name', f'Rule {rule_id}')
            
            # Evaluate the rule against this email
            if evaluate_rule(email, rule):
                print(f"Rule '{rule_name}' matched email: {email['subject'][:40]}...")
                
                # Apply all actions for this rule
                for action in rule.get('actions', []):
                    action_type = action.get('type', '')
                    action_value = action.get('value', '')
                    
                    result = apply_action(service, email, action)
                    
                    if result:
                        actions_applied += 1
                        print(f"  - Action applied: {action_type} -> {result}")
                        
                        # Record the action in the database
                        record_rule_action(
                            email['id'], 
                            rule_id, 
                            action_type, 
                            str(action_value)
                        )
    
    print(f"Applied {actions_applied} actions based on rules.")
    return actions_applied

def main():
    # Get the Gmail service
    gmail_service = get_gmail_service()
    
    if not gmail_service:
        print("Failed to initialize Gmail service. Exiting.")
        return
    
    print("Successfully connected to Gmail API.")
    
    # Process emails with rules
    process_emails_with_rules(gmail_service)

if __name__ == '__main__':
    main()