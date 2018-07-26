# coding: utf-8

# In[1]:


def greeting(name):
    return 'Hi ' + name + '. How are you?'


# In[2]:


default_name = 'Dave'


# In[3]:


# # nuclio:ignore
# from nuclio import Context, Event
# context = Context()
# event = Event(body=default_name)


# In[4]:


def handler(context, event):
    # nuclio:handler
    return greeting(event.body)

