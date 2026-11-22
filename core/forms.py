from django import forms

from .models import Comment, Recommendation, Title, Watched


class SearchForm(forms.Form):
    q = forms.CharField(label="Title", max_length=150, widget=forms.TextInput(attrs={"type": "search"}))


class ImportForm(forms.Form):
    media_type = forms.ChoiceField(choices=Title.Media)
    tmdb_id = forms.IntegerField(min_value=1, max_value=2**63 - 1)


class WatchedForm(forms.ModelForm):
    class Meta:
        model = Watched
        fields = ["rating", "review"]
        widgets = {"rating": forms.NumberInput(attrs={"min": 0, "max": 10, "step": "0.5"}),
                   "review": forms.Textarea(attrs={"rows": 4})}


class MessageForm(forms.ModelForm):
    class Meta:
        model = Recommendation
        fields = ["message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 3})}


class StatusForm(forms.ModelForm):
    class Meta:
        model = Recommendation
        fields = ["status"]


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Recommendation
        fields = ["feedback"]
        widgets = {"feedback": forms.Textarea(attrs={"rows": 3})}


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        labels = {"body": "Comment"}
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}


class PickForm(forms.Form):
    title = forms.ModelChoiceField(queryset=Title.objects.none())

    def __init__(self, user, excluded, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].queryset = Title.objects.filter(watched__user=user).exclude(pk__in=excluded)
